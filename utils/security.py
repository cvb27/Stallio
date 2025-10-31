from werkzeug.security import generate_password_hash, check_password_hash

"""
Helpers de seguridad unificados a pbkdf2:sha256 (Werkzeug).
- hash_password: genera hash pbkdf2:sha256.
- verify_password: verifica pbkdf2:sha256.
No hay fallback. Así simplificamos y evitamos mezclar formatos.
"""


# --- Password hashing helpers ---
def hash_password(plain: str) -> str:
    """
    Devuelve un hash tipo: pbkdf2:sha256:<iteraciones>$<salt>$<hash>
    Este es el formato que tu login ya usa en producción.
    """
    return generate_password_hash(plain, method="pbkdf2:sha256", salt_length=16)



def verify_password(plain: str, hashed: str) -> bool:
    """
    Verifica contra pbkdf2:sha256. Si el hash no es de este tipo (p.ej. $2b$...),
    devolverá False y el login fallará (lo correcto si el usuario no ha pasado por el reset).
    """
    return check_password_hash(hashed, plain)

