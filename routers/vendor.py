from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from db import get_session
from models import User, Product, PaymentReport, VendorBranding, DEFAULT_BRANDING_SETTINGS
from typing import Optional
from copy import deepcopy
from datetime import datetime
from routers.store_helpers import resolve_store, get_branding_by_owner, ensure_settings_dict, norm_instagram, norm_whatsapp,build_theme
from storage_local import save_vendor_bytes
import re, unicodedata
import logging
log = logging.getLogger("uvicorn.error")  # usa el logger de Uvicorn

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
       
    """
    Crea/actualiza la configuración de marca del vendor.
    - Persiste el logo en el volumen /uploads (vía save_vendor_bytes)
    - Guarda la URL del logo en settings["logo_url"]
    - Reasigna 'branding.settings' al final para garantizar persistencia
    """

    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    # 1) Carga el registro a editar (por ID del form o el más reciente del owner)
    branding = None
    if branding_id:
        branding = session.exec(
            select(VendorBranding).where(
                VendorBranding.id == branding_id,
                VendorBranding.owner_id == owner_id
            )
        ).first()
    if not branding:
        branding = get_branding_by_owner(session, owner_id)
    
    # 2) fallback al más reciente por owner
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
        session.commit()
        session.refresh(branding)

     # 3) Actualizamos metadatos básicos
    branding.display_name = (display_name or "Mi Tienda").strip()
    branding.updated_at = datetime.utcnow()

    # 4) Preparar dict de settings (con defaults) y escribir los campos del form
    settings = ensure_settings_dict(getattr(branding, "settings", None))
    settings["tagline"]   = (tagline or "").strip()
    settings["whatsapp"]  = norm_whatsapp(whatsapp or "")
    settings["instagram"] = norm_instagram(instagram or "")
    settings["location"]  = (location or "").strip() 

    # 5) cambio de slug (opcional)
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

    # 6) LOGO (persistente en volumen /uploads/vendors/<slug>/file)
    #    Asegura que realmente guardamos el archivo y que settings.logo_url queda guardado.
    if logo and getattr(logo, "filename", ""):
        # Validaciones mínimas
        ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/svg+xml", "image/gif"}
        if logo.content_type not in ALLOWED:
            return RedirectResponse("/vendor/brand?err=Formato+no+permitido", status_code=302)

        content = await logo.read()
        if not content:
            return RedirectResponse("/vendor/brand?err=Archivo+vacío", status_code=302)
        
        if len(content) > 3 * 1024 * 1024:  # 3MB
            return RedirectResponse("/vendor/brand?err=Archivo+muy+grande+(3MB)", status_code=302)

        # slug de carpeta para el vendor
        vendor = session.exec(select(User).where(User.id == owner_id)).first()
        vendor_slug = vendor.slug if vendor and vendor.slug else branding.slug.strip()

        # Guarda físicamente en el volumen y trae URL pública /uploads/...
        public_url = save_vendor_bytes(vendor_slug, content, logo.filename)

        # Escribe SIEMPRE en settings.logo_url (fuente de verdad)
        settings = ensure_settings_dict(getattr(branding, "settings", None))
        settings["logo_url"] = public_url
        branding.settings = settings  # <-- importante: reasignar

        # Compatibilidad: también completa la columna plana si existe
        # (no se usa para render, pero no hace daño)
        try:
            branding.logo_url = public_url
        except Exception:
            pass

        # Sube el updated_at para que el cache-buster del <img> cambie
        branding.updated_at = datetime.utcnow()

        # DEBUG opcional
        log.info(f"[brand_save] Logo guardado para {vendor_slug}: {public_url}")

    """
        # guarda la URL en settings (o en columna propia si prefieres)
        settings["logo_url"] = public_url

    session.add(branding)
    session.commit()
    session.refresh(branding)
    return RedirectResponse("/vendor/brand?ok=1", status_code=302)
    """