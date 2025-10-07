
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from db import get_session
from models import VendorBranding, User
from pathlib import Path
import os

router = APIRouter()

@router.get("/debug/branding/{slug}")
def dbg_branding(slug: str, session: Session = Depends(get_session)):
    # Busca branding por slug o por owner
    b = session.exec(select(VendorBranding).where(VendorBranding.slug == slug)).first()
    if not b:
        u = session.exec(select(User).where(User.slug == slug)).first()
        if not u: return JSONResponse({"error":"no user/branding"}, status_code=404)
        b = session.exec(select(VendorBranding).where(VendorBranding.owner_id == u.id)).first()
        if not b: return JSONResponse({"error":"no branding for user"}, status_code=404)
    return {
        "branding_id": b.id,
        "slug": b.slug,
        "owner_id": b.owner_id,
        "display_name": b.display_name,
        "settings": b.settings,
        "logo_url": (b.settings or {}).get("logo_url"),
        "updated_at": str(b.updated_at),
    }

@router.get("/debug/uploads/{vendor_slug}")
def dbg_uploads(vendor_slug: str):
    root = Path("uploads") / "vendors" / vendor_slug
    if not root.exists():
        return {"exists": False, "path": str(root)}
    files = []
    for p in root.glob("*"):
        if p.is_file():
            files.append({"name": p.name, "size": p.stat().st_size})
    return {"exists": True, "path": str(root.resolve()), "files": files}
