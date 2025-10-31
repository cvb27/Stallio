from typing import Optional, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired


# Helpers de seguridad unificados a pbkdf2:sha256 (Werkzeug).
# - hash_password: genera hash pbkdf2:sha256.
# - verify_password: verifica pbkdf2:sha256.
# No hay fallback. Así simplificamos y evitamos mezclar formatos.

# ---- Password hashing (pbkdf2:sha256, consistente con login) ----
def hash_password(plain: str) -> str:
    return generate_password_hash(plain, method="pbkdf2:sha256", salt_length=16)

def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)

# ---- Reset token helpers (stateless con versionado) ----

# Token payload is (user_id, version). It's signed + timestamped.
# We don't store tokens in DB; instead, we store a per‑user 'version'.
# After a successful reset we increment version → all older tokens die.
def make_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="stallio:pwdreset")

def generate_reset_token(secret_key: str, user_id: int, version: int) -> str:
    s = make_serializer(secret_key)
    return s.dumps((user_id, version))

def verify_reset_token(
    secret_key: str, token: str, max_age: int
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Returns: (user_id, version, error)
    error: None | "expired" | "invalid"
    """
    s = make_serializer(secret_key)
    try:
        user_id, version = s.loads(token, max_age=max_age)
        return user_id, version, None
    except SignatureExpired:
        return None, None, "expired"
    except BadSignature:
        return None, None, "invalid"



