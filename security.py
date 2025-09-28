
from passlib.context import CryptContext
from hashlib import sha256
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

def hash_password(password: str) -> str:
    # Puedes usar "pbkdf2:sha256" (default) o "scrypt"/"argon2" si prefieres
    return generate_password_hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)