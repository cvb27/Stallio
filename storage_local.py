import os, uuid, mimetypes
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_UPLOADS = str((BASE_DIR.parent / "uploads").resolve()) if (BASE_DIR / "uploads").exists() else str((Path.cwd() / "uploads").resolve())
UPLOADS_DIR = os.getenv("UPLOADS_DIR", DEFAULT_LOCAL_UPLOADS).rstrip("/")

def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def _ext_from_name(name: str) -> str:
    name = (name or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if name.endswith(ext):
            return ext
    guess = mimetypes.guess_extension(mimetypes.guess_type(name)[0] or "")
    return guess or ".bin"

def save_vendor_bytes(vendor_slug: str, content: bytes, filename: str) -> str:
    """
    Guarda bytes en:  <UPLOADS_DIR>/vendors/<slug>/<uuid>.<ext>
    y retorna URL pública: /uploads/vendors/<slug>/<file>
    (asumiendo que /uploads está montado vía StaticFiles)
    """
    ext = _ext_from_name(filename)
    rel = f"vendors/{vendor_slug}/{uuid.uuid4().hex}{ext}"
    base = Path(UPLOADS_DIR)
    _ensure_dir(base / f"vendors/{vendor_slug}")
    (base / rel).write_bytes(content)
    return f"/uploads/{rel}"

