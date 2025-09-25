
from config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, SELLER_MOBILE

def send_sms(to: str, body: str) -> bool:
    """
    Envía SMS vía Twilio. Si las variables no están configuradas,
    no falla: solo imprime y retorna False.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER and to):
        print("[sms] (simulado) →", to, body)
        return False

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            to=to,
            from_=TWILIO_FROM_NUMBER,
            body=body,
        )
        print("[sms] enviado:", msg.sid)
        return True
    except Exception as e:
        print("[sms] error:", e)
        return False
