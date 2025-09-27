import os

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
SMTP_HOST = "smtp.gmail.com"       # o el de tu proveedor
SMTP_PORT = 465                    # 465 (SSL) o 587 (STARTTLS)
SMTP_USER = "tu_correo@gmail.com"
SMTP_PASS = "tu_password_o_app_password"
SMTP_FROM = "no-reply@tudominio.com"  # remitente visible

# Credenciales Twilio (SMS). Si no están, el envío se omite y se loggea.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")  # formato +1XXX...
SELLER_MOBILE      = os.getenv("SELLER_MOBILE", "")       # a dónde avisar

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")  
RESET_TOKEN_TTL_MIN = int(os.getenv("RESET_TOKEN_TTL_MIN", "60"))  # 60 min
MAIL_FROM = os.getenv("MAIL_FROM", "no-reply@tu-dominio")
