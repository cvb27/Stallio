# storage_local.py
import os, uuid, mimetypes
from pathlib import Path

# Raíz de uploads (persistente). En prod define UPLOADS_DIR=/uploads (volumen).
def get_uploads_dir() -> Path:
    base = os.getenv("UPLOADS_DIR")
    return Path(base).resolve() if base else (Path(__file__).resolve().parent.parent / "uploads").resolve()

def _safe_ext(name: str) -> str:
    name = (name or "").lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if name.endswith(ext): return ext
    ctype, _ = mimetypes.guess_type(name)
    return (mimetypes.guess_extension(ctype or "") or ".bin")

def _save_bytes(rel_path: Path, content: bytes) -> str:
    root = get_uploads_dir()
    dst = root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(content)
    # URL pública bajo /uploads
    return f"/uploads/{rel_path.as_posix()}"

def save_vendor_logo(slug: str, content: bytes, filename: str) -> str:
    ext = _safe_ext(filename)
    rel = Path("vendors") / slug / f"{uuid.uuid4().hex}{ext}"
    return _save_bytes(rel, content)

def save_product_image(slug: str, content: bytes, filename: str) -> str:
    ext = _safe_ext(filename)
    rel = Path("products") / slug / f"{uuid.uuid4().hex}{ext}"
    return _save_bytes(rel, content)
