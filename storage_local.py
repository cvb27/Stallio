import os, uuid, mimetypes
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# En prod leemos UPLOADS_DIR del entorno (ej. /uploads).
# En local, por defecto usamos ./uploads en la raíz del repo.
DEFAULT_LOCAL_UPLOADS = (BASE_DIR.parent / "uploads").resolve()
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(DEFAULT_LOCAL_UPLOADS))).resolve()


"""Detecta extensión segura a partir del nombre"""
def _ext_from_name(name: str) -> str:
    name = (name or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if name.endswith(ext):
            return ext
    ctype, _ = mimetypes.guess_type(name)
    guess = mimetypes.guess_extension(ctype or "")
    return guess or ".bin"

"""
    Guarda el contenido en /uploads/vendors/<slug>/<uuid>.<ext>
    Devuelve la URL pública /uploads/vendors/<slug>/<file>
    """
def save_vendor_bytes(vendor_slug: str, content: bytes, filename: str) -> str:
    ext = _ext_from_name(filename)
    rel = Path("vendors") / vendor_slug / f"{uuid.uuid4().hex}{ext}"
    dest_path = UPLOADS_DIR / rel
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)
    # URL pública
    return f"/uploads/{rel.as_posix()}"
    # return f"/uploads/vendors/{slug}/{safe_name}"
    

