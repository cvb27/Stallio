from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from db import get_session
from models import User, Product, PaymentReport, VendorBranding, DEFAULT_BRANDING_SETTINGS
from typing import Optional
from fastapi import Form
from copy import deepcopy
from datetime import datetime
from routers.store_helpers import resolve_store, get_branding_by_owner, ensure_settings_dict, norm_instagram, norm_whatsapp,build_theme
import re, unicodedata, os, time

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def _require_vendor_own(request: Request, session: Session, slug: str) -> Optional[User]:
    """Devuelve el User si el slug corresponde al usuario logueado; si no, None."""
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    vendor = session.exec(select(User).where(User.slug == slug)).first()
    if not vendor or vendor.id != request.session["user_id"]:
        return None
    return vendor

def _slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9-]+', '-', text.lower()).strip('-')
    return text or 'tienda'

def _unique_slug(session: Session, wanted: str) -> str:
    base = _slugify(wanted)
    slug, i = base, 2
    while session.exec(select(VendorBranding).where(VendorBranding.slug == slug)).first():
        slug = f"{base}-{i}"; i += 1
    return slug

# Vista/preview para el vendor (usa el mismo template que la pública)
@router.get("/vendor/home", response_class=HTMLResponse)
async def vendor_home(request: Request, session: Session = Depends(get_session)):
    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    user = session.exec(select(User).where(User.id == owner_id)).first()
    branding = get_branding_by_owner(session, owner_id)
    products = session.exec(select(Product).where(Product.owner_id == owner_id)).all()
    theme = build_theme(branding)
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "branding": branding,
        "vendor": user,
        "products": products,
        "theme": theme,
    })

# Dashboard admin
@router.get("/admin/{slug}/dashboard", response_class=HTMLResponse)
def vendor_dashboard(slug: str, request: Request, session: Session = Depends(get_session)):
    vendor = _require_vendor_own(request, session, slug)
    if not vendor:
        return RedirectResponse("/login", status_code=302)

    # SOLO sus productos y pedidos
    products = session.exec(select(Product).where(Product.owner_id == vendor.id)).all()
    reports  = session.exec(
        select(PaymentReport).where(PaymentReport.owner_id == vendor.id).order_by(PaymentReport.id.desc())
    ).all()

    branding = get_branding_by_owner(session, vendor.id)  # <-- agrega si tu layout lo usa

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "vendor": vendor,
        "products": products,
        "reports": reports,
        "branding": branding,  # <-- opcional
    })

# ÚNICA ruta pública canónica
@router.get("/u/{slug}", response_class=HTMLResponse)
def public_store(
    slug: str, 
    request: Request, 
    session: Session = Depends(get_session)):
    user, branding = resolve_store(session, slug)

    products = session.exec(select(Product).where(Product.owner_id == user.id)).all()
    theme = build_theme(branding)
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "branding": branding,
        "vendor": user,
        "products": products,
        "theme": theme,
        
    })

# Form "Editar mi página"
@router.get("/vendor/brand", response_class=HTMLResponse)
async def brand_form(
    request: Request, 
    session: Session = Depends(get_session)):
    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")

    branding = get_branding_by_owner(session, owner_id)
    if not branding:
        # crear con slug por defecto basado en User.slug o "tienda-{id}"
        user = session.exec(select(User).where(User.id == owner_id)).first()
        base = user.slug if user and getattr(user, "slug", None) else f"tienda-{owner_id}"
        branding = VendorBranding(
            owner_id=owner_id,
            slug=_unique_slug(session, base),
            display_name="Mi Tienda",
            settings=deepcopy(DEFAULT_BRANDING_SETTINGS),
        )
        session.add(branding)
        session.commit()
        session.refresh(branding)
        

    return templates.TemplateResponse("admin/brand_form.html", {
        "request": request,
        "branding": branding
    })

# Guardar cambios del branding
@router.post("/vendor/brand", response_class=HTMLResponse)
async def brand_save(
    request: Request,
    session: Session = Depends(get_session),
    display_name: str = Form(...),
    slug: Optional[str] = Form(None),
    branding_id: Optional[int] = Form(None),
    tagline: Optional[str] = Form(None),      
    whatsapp: Optional[str] = Form(None),     
    instagram: Optional[str] = Form(None),
    logo: UploadFile | None = File(None),
    location: Optional[str] = Form(None),
):
       
    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    
     # 1) intenta cargar por ID exacto + owner
    branding = None
    if branding_id:
        branding = session.exec(
            select(VendorBranding).where(
                VendorBranding.id == branding_id,
                VendorBranding.owner_id == owner_id
            )
        ).first()
    
    # 2) fallback al más reciente por owner
    if not branding:
        branding = get_branding_by_owner(session, owner_id)

    created_now = False
    if not branding:
        user = session.exec(select(User).where(User.id == owner_id)).first()
        base = user.slug if user and getattr(user, "slug", None) else f"tienda-{owner_id}"
        branding = VendorBranding(
            owner_id=owner_id,
            slug=_unique_slug(session, base),
            display_name=(display_name or "Mi Tienda").strip(),
            settings=deepcopy(DEFAULT_BRANDING_SETTINGS),
        )
        session.add(branding)
    else:
        branding.display_name = (display_name or "Mi Tienda").strip()
        branding.updated_at = datetime.utcnow()

    # 3) actualizar SETTINGS (siempre como dict con defaults)
    branding.settings = ensure_settings_dict(getattr(branding, "settings", None))
    branding.settings["tagline"]   = (tagline or "").strip()
    branding.settings["whatsapp"]  = norm_whatsapp(whatsapp or "")
    branding.settings["instagram"] = norm_instagram(instagram or "")
    branding.settings["location"]  = (location or "").strip() 

    # 4) cambio de slug (opcional)
    if slug is not None:
        wanted = _slugify(slug)
        if wanted and wanted != branding.slug:
            new_slug = _unique_slug(session, wanted)
            user = session.exec(select(User).where(User.id == owner_id)).first()
            if user:
                conflict = session.exec(
                    select(User).where(User.slug == new_slug, User.id != owner_id)
                ).first()
                if conflict:
                    return RedirectResponse("/vendor/brand?err=Slug+ya+en+uso", status_code=302)
                user.slug = new_slug
            branding.slug = new_slug

    if logo and getattr(logo, "filename", ""):
        if logo.content_type not in ("image/png", "image/jpeg", "image/webp"):
            # si quieres, puedes ignorar o redirigir con error
            pass
        else:
            os.makedirs("static/uploads", exist_ok=True)
            _, ext = os.path.splitext(logo.filename)
            ext = ext.lower() if ext.lower() in (".png", ".jpg", ".jpeg", ".webp") else ".png"
            filename = f"logo_{owner_id}_{int(time.time())}{ext}"
            dest_path = os.path.join("static", "uploads", filename)
            content = await logo.read()
            with open(dest_path, "wb") as f:
                f.write(content)
            # URL pública
            branding.settings["logo_url"] = f"/static/uploads/{filename}"

    session.commit()
    session.refresh(branding)
    return RedirectResponse("/vendor/brand?ok=1", status_code=302)
