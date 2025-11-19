from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from templates_engine import templates
from sqlmodel import Session
from db import get_session
from models import User
from urllib.parse import quote
import io

router = APIRouter(prefix="/admin/share", tags=["Admin Share"])

def _require_vendor(request: Request) -> int:
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(request.session["user_id"])

def _public_url(request: Request, vendor: User) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/u/{vendor.slug}"

@router.get("/", response_class=HTMLResponse)
def share_page(request: Request, session: Session = Depends(get_session)):
    owner_id = _require_vendor(request)
    vendor = session.get(User, owner_id)
    public_url = _public_url(request, vendor)
    return templates.TemplateResponse("/admin/share.html", {
        "request": request,
        "vendor": vendor,
        "public_url": public_url
    })

@router.get("/qr.png")
def share_qr_png(request: Request, session: Session = Depends(get_session)):
    """
    Genera PNG del QR en el servidor si hay librería `qrcode` instalada.
    Si no, hace fallback a un generador público.
    """
    owner_id = _require_vendor(request)
    vendor = session.get(User, owner_id)
    public_url = _public_url(request, vendor)

    try:
        import qrcode  # pip install qrcode[pil]
        img = qrcode.make(public_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})
    except Exception:
        # Fallback sencillo (no cachea aquí, es un redirect al generador)
        return RedirectResponse(
            f"https://api.qrserver.com/v1/create-qr-code/?size=512x512&data={quote(public_url)}",
            status_code=302
        )