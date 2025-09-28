import asyncio
from typing import Set
from starlette.websockets import WebSocket
import smtplib, ssl
from email.message import EmailMessage
from typing import Optional
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_TLS, EMAIL_FROM,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
)

# gestor mínimo de conexiones WS

class WSManager:
    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: str):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = WSManager()




def send_email(to: str, subject: str, html: str, text_alt: Optional[str] = None):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and SMTP_FROM and to):
        print("[notify] Email DESACTIVADO o datos incompletos. Para:", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_alt or subject)
    msg.add_alternative(html, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    return True

__all__ = ["send_email", "send_sms"]