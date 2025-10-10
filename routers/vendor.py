from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from db import get_session
from models import User, Product, PaymentReport, VendorBranding, DEFAULT_BRANDING_SETTINGS
from typing import Optional
from copy import deepcopy
from datetime import datetime
from routers.store_helpers import resolve_store, get_branding_by_owner, ensure_settings_dict, norm_instagram, norm_whatsapp, build_theme
from storage_local import save_vendor_bytes
import re, unicodedata
import logging
log = logging.getLogger("uvicorn.error")  # usa el logger de Uvicorn

router = APIRouter()
templates = Jinja2Templates(directory="templates")

def _current_owner_id(request: Request) -> int:
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="No autenticado")
    return int(uid)

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

@router.get("/u/{slug}/products.json")
def public_products_json(slug: str, session: Session = Depends(get_session)):
    user, _ = resolve_store(session, slug)  # importa resolve_store desde store_helpers
    rows = session.exec(select(Product).where(Product.owner_id == user.id)).all()
    return [{
        "id": p.id,
        "name": p.name,
        "price": p.price,
        "stock": p.stock,
        "image_url": p.image_url or "/static/img/product_placeholder.png",
        "created_at": p.created_at.isoformat(),
    } for p in rows]


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
@router.get("/vendor/brand", name="brand_form", response_class=HTMLResponse)
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
@router.post("/vendor/brand")
async def brand_save(
    request: Request,
    session: Session = Depends(get_session),
    display_name: str = Form(...),
    logo: UploadFile | None = File(None),
):
    owner_id = _current_owner_id(request)
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.owner_id == owner_id)
    ).first()

    if not branding:
        # crea si no existe
        user = session.exec(select(User).where(User.id == owner_id)).first()
        slug = user.slug if user and user.slug else f"tienda-{owner_id}"
        branding = VendorBranding(
            owner_id=owner_id, slug=user.slug, display_name=display_name, settings={}
        )
    
        session.add(branding); 
        session.commit(); 
        session.refresh(branding)

    branding.display_name = display_name.strip()
    branding.updated_at = datetime.utcnow()

    if logo and getattr(logo, "filename", ""):
        content = await logo.read()
        if not content:
            raise HTTPException(status_code=400, detail="Logo vacío")
        # Guarda en volumen y persiste la URL pública en settings.logo_url
        public_url = save_vendor_bytes(branding.slug, content, logo.filename)
        settings = ensure_settings_dict(branding.settings)
        settings["logo_url"] = public_url
        branding.settings = settings

    session.add(branding); 
    session.commit(); 
    session.refresh(branding)
    
    return RedirectResponse("/vendor/brand?ok=1", status_code=302)
"""
    return templates.TemplateResponse("admin/brand_form.html", {
        "request": request,
        "branding": branding
    })
"""    
    
    # return {"ok": True, "branding_id": branding.id, "logo_url": branding.logo_url}