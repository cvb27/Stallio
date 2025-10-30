from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional, Tuple


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- Password hashing helpers ---
def hash_password(plain: str) -> str:
    """Return a salted secure hash for storage."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant‑time verify of a plain password against its hash."""
    return pwd_context.verify(plain, hashed)


# --- Reset token helpers ---
# Token payload is (user_id, version). It's signed + timestamped.
# We don't store tokens in DB; instead, we store a per‑user 'version'.
# After a successful reset we increment version → all older tokens die.


def make_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="stallio:pwdreset")


def generate_reset_token(secret_key: str, user_id: int, version: int) -> str:
    s = make_serializer(secret_key)
    return s.dumps((user_id, version))


def verify_reset_token(secret_key: str, token: str, max_age: int) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Returns: (user_id, version, error)
    error is None if ok, or a short message ("expired" / "invalid").
    """
    s = make_serializer(secret_key)
    try:
        user_id, version = s.loads(token, max_age=max_age)
        return user_id, version, None
    except SignatureExpired:
        return None, None, "expired"
    except BadSignature:
        return None, None, "invalid"