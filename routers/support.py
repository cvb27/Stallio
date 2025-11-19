from fastapi import APIRouter, Request, HTTPException, Depends
from templates_engine import templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from models import User
from db import get_session
import os
from urllib.parse import quote

router = APIRouter()

def _env(key: str, default: str) -> str:
    return os.getenv(key, default).strip()

# Entrada sin slug -> redirige al slug del vendor en sesión
@router.get("/admin/support")
async def support_shortcut(request: Request, session: Session = Depends(get_session)):
    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=302)
    user = session.get(User, int(request.session["user_id"]))
    if not user:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse(f"/admin/{user.slug}/support", status_code=302)

# Ajustado nombre de función, mismo path con slug.
@router.get("/admin/{slug}/support", response_class=HTMLResponse)
async def support_page(slug: str, request: Request, session: Session = Depends(get_session)):
    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=302)

    vendor = session.exec(select(User).where(User.slug == slug)).first()
    if not vendor or vendor.id != request.session["user_id"]:
        raise HTTPException(status_code=403, detail="No autorizado")

    # === Configurable por ENV ===
    BRAND             = _env("SUPPORT_BRAND", "Mi Tienda")
    SUPPORT_EMAIL     = _env("SUPPORT_EMAIL", "soporte@mitienda.com")
    SUPPORT_WA_NUMBER = _env("SUPPORT_WHATSAPP", "17861234567")  # solo dígitos
    SUPPORT_TG_URL    = _env("SUPPORT_TELEGRAM_URL", "https://t.me/mi_grupo_soporte")

    # Mensajes prellenados
    subject = f"Soporte — {BRAND}"
    body    = f"Hola {BRAND}, necesito ayuda con mi pedido."

    # Links
    mailto_link = f"mailto:{SUPPORT_EMAIL}?subject={quote(subject)}&body={quote(body)}"
    wa_link     = f"https://wa.me/{SUPPORT_WA_NUMBER}"
    tg_link     = SUPPORT_TG_URL

    ctx = {
        "request": request,
        "brand": BRAND,
        "support_email": SUPPORT_EMAIL,
        "mailto_link": mailto_link,
        "wa_link": wa_link,
        "tg_link": tg_link,
    }
    return templates.TemplateResponse("admin/support.html", ctx)


