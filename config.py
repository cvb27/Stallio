import os

ENV = os.getenv("ENV", "local")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

# config.py - mínimo para probar
SESSION_SECRET = "dev-secret"
ADMIN_EMAIL = "admin@local"
ADMIN_PASSWORD = "admin123"

# Información que verá el cliente para pagar (muestra lo que uses tú)
PAYMENT_INFO = {
    "title": "Pagos via ZELLE",
    "zelle": "email@example.com (Nombre Apellido)",
    "btc": "bc1qexampleaddress...",  # opcional
    #"notes": "Envía el comprobante indicando tu nombre y producto.",
}

# Correos salientes (SMTP)
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() in ("1", "true", "yes")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Stallio <no-reply@stallio.app>")

# Credenciales Twilio (SMS). Si no están, el envío se omite y se loggea.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")  # formato +1XXX...
SELLER_MOBILE      = os.getenv("SELLER_MOBILE", "")       # a dónde avisar

  
RESET_TOKEN_TTL_MIN = int(os.getenv("RESET_TOKEN_TTL_MIN", os.getenv("RESET_TOKEN_MINUTES", "30")))
MAIL_FROM = os.getenv("MAIL_FROM", "no-reply@tu-dominio")
