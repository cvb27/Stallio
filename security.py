
from passlib.context import CryptContext
from hashlib import sha256
import secrets

# bcrypt es seguro, rápido de verificar y ampliamente soportado
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"  # permite migrar desde hashes antiguos si algún día cambias
)

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    # Devuelve False si el hash es inválido o el esquema no es reconocido
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False
