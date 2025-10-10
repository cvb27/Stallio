# storage_local.py
import os, uuid, mimetypes
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_UPLOADS = (BASE_DIR.parent / "uploads").resolve()
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", str(DEFAULT_LOCAL_UPLOADS))).resolve()


def _ext_from_name(name: str) -> str:
    """Devuelve una extensión segura a partir del nombre."""
    name = (name or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if name.endswith(ext):
            return ext
    ctype, _ = mimetypes.guess_type(name)
    return (mimetypes.guess_extension(ctype or "") or ".bin")

def save_vendor_bytes(vendor_slug: str, content: bytes, filename: str) -> str:
    """Guarda logos en <UPLOADS_DIR>/vendors/<slug>/<uuid>.<ext> y retorna /uploads/..."""
    ext = _ext_from_name(filename)
    rel = Path("vendors") / vendor_slug / f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return f"/uploads/{rel.as_posix()}"

def save_product_bytes(vendor_slug: str, content: bytes, filename: str) -> str:
    """Guarda fotos de producto en <UPLOADS_DIR>/products/<slug>/<uuid>.<ext> y retorna /uploads/..."""
    ext = _ext_from_name(filename)
    rel = Path("products") / vendor_slug / f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return f"/uploads/{rel.as_posix()}"