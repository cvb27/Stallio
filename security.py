# security.py
import secrets
from hashlib import sha256

def hash_password(plain: str, salt: str | None = None) -> tuple[str, str]:
    """
    Devuelve (password_hash, salt). Si no pasas salt, genera una sal segura.
    Hash = sha256( sal + contraseña_plana )
    """
    if salt is None:
        salt = secrets.token_hex(16)  # 32 chars hex
    h = sha256((salt + plain).encode("utf-8")).hexdigest()
    return h, salt

def verify_password(plain: str, salt: str, stored_hash: str) -> bool:
    """
    Recalcula el hash con la sal y compara con el hash almacenado.
    """
    h = sha256((salt + plain).encode("utf-8")).hexdigest()
    return secrets.compare_digest(h, stored_hash)
