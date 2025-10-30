import os
from typing import Optional


"""
    En desarrollo: imprime el correo en consola.
    En producción: si EMAIL_DEV_PRINT=0, envía por SMTP (ej. IONOS).
    """

def send_email(to_email: str, subject: str, body_text: str) -> None:
    """Ultra‑minimal sender. Swap with your SMTP when ready."""
    if os.getenv("EMAIL_DEV_PRINT", "1") == "1":
        print("\n===== EMAIL (DEV PRINT) =====")
        print("TO:", to_email)
        print("SUBJECT:", subject)
        print("BODY:\n", body_text)
        print("===========================\n")
        return


    # --- SMTP real ---

    import smtplib
    from email.message import EmailMessage


    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASS = os.getenv("SMTP_PASS")
    SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)

    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM]):
        raise RuntimeError("SMTP vars missing: set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM")

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)


    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
