from fastapi import APIRouter, Request, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from templates_engine import templates
from sqlmodel import Session, select
from db import get_session

from models import User, Product, PaymentReport, VendorBranding, DEFAULT_BRANDING_SETTINGS, Order, OrderItem, Review
from utils.reviews import compute_avg_rating

from typing import Optional
from copy import deepcopy
from datetime import datetime
from routers.store_helpers import resolve_store, get_branding_by_owner, ensure_settings_dict, norm_instagram, norm_whatsapp, build_theme
from storage_local import save_vendor_bytes
import re, unicodedata
import logging

log = logging.getLogger("uvicorn.error")  # usa el logger de Uvicorn

router = APIRouter()

# ---------------------------
# Helpers de sesión/seguridad
# ---------------------------

def _current_owner_id(request: Request) -> int:
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="No autenticado")
    return int(uid)

def _require_vendor_own(request: Request, session: Session, slug: str) -> Optional[User]:
    """Devuelve el User si el slug corresponde al usuario logueado; si no, None.
    Mantiene compatibilidad con el flujo actual del dashboard."""

    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    vendor = session.exec(select(User).where(User.slug == slug)).first()
    if not vendor or vendor.id != request.session["user_id"]:
        return None
    return vendor

# ---------------------------
# Helpers de branding/slug
# ---------------------------

def _slugify(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-zA-Z0-9-]+', '-', text.lower()).strip('-')
    return text or 'tienda'

def _unique_slug(session: Session, wanted: str) -> str:

    """
    Devuelve un slug único a partir de 'wanted', probando sufijos -2, -3, ...
    sobre la tabla VendorBranding.slug (que es lo que se expone públicamente).
    """
     
    base = _slugify(wanted)
    slug, i = base, 2
    while session.exec(select(VendorBranding).where(VendorBranding.slug == slug)).first():
        slug = f"{base}-{i}"; i += 1
    return slug

# --------------------------------------------
# Vista/preview para el vendor (usa template público)
# --------------------------------------------

@router.get("/vendor/home", response_class=HTMLResponse)
async def vendor_home(
    request: Request, 
    session: Session = Depends(get_session)):

    """
    Vista de preview del vendor usando el mismo template público.
    CHG:
    - Ahora también carga reviews aprobadas,
      el promedio y el conteo, igual que /u/{slug}.
    """

    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    user = session.exec(select(User).where(User.id == owner_id)).first()
    branding = get_branding_by_owner(session, owner_id)
    products = session.exec(select(Product).where(Product.owner_id == owner_id)).all()
    theme = build_theme(branding)

    # CHG: reviews aprobadas del vendor (preview ve lo mismo que el público)
    reviews = session.exec(
        select(Review)
        .where(Review.vendor_id == user.id)
        .where(Review.is_approved == True)
        .order_by(Review.created_at.desc())
        .limit(20)
    ).all()

    avg_rating = compute_avg_rating(reviews)
    reviews_count = len(reviews)

    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "branding": branding,
        "vendor": user,
        "products": products,
        "theme": theme,
        "reviews": reviews,               # CHG
        "avg_rating": avg_rating,         # CHG
        "reviews_count": reviews_count,   # CHG
    })

# ----------------
# Dashboard admin
# ----------------

@router.get("/admin/{slug}/dashboard", response_class=HTMLResponse)
def vendor_dashboard(slug: str, request: Request, session: Session = Depends(get_session)):
    vendor = _require_vendor_own(request, session, slug)
    if not vendor:
        return RedirectResponse("/login", status_code=302)

    # SOLO sus productos y pedidos
    products = session.exec(select(Product).where(Product.owner_id == vendor.id)).all()

    # CHG: Antes: .where(PaymentReport.owner_id == vendor.id) -> ya NO existe owner_id.
    # Ahora: PaymentReport -> Order -> OrderItem -> Product; filtro por Product.vendor_id == vendor.id
    # group_by para evitar duplicados si un mismo order tiene varios items del vendor.
    
    reports_q = (
        select(PaymentReport)
        .join(Order, PaymentReport.order_id == Order.id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Product.owner_id == vendor.id)    # Nota: si tu modelo usa vendor_id, cambia aquí a vendor_id
        .group_by(PaymentReport.id)
        .order_by(PaymentReport.id.desc())
    )
    reports = session.exec(reports_q).all()

    branding = get_branding_by_owner(session, vendor.id)  # <-- agrega si tu layout lo usa

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "vendor": vendor,
        "products": products,
        "reports": reports,
        "branding": branding,  # <-- opcional
    })

# --------------------------
# API pública (JSON productos)
# --------------------------

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

# -------------------------
# ÚNICA ruta pública canónica
# -------------------------

@router.get("/u/{slug}", response_class=HTMLResponse)
def public_store(
    slug: str, 
    request: Request, 
    session: Session = Depends(get_session)):

    """
    Página pública del vendor.
    Carga:
    - vendor (User)
    - branding
    - products
    - reviews aprobadas
    - promedio de rating
    """

    # 1) Resolver vendor y branding a partir del slug público
    user, branding = resolve_store(session, slug)

     # 2) Productos del vendor
    products = session.exec(
        select(Product).where(Product.owner_id == user.id)
        ).all()
    
    theme = build_theme(branding)

    # 3) Reviews aprobadas del vendor
    reviews = session.exec(
        select(Review)
        .where(Review.vendor_id == user.id)
        .where(Review.is_approved == True)
        .order_by(Review.created_at.desc())
        .limit(20)
    ).all()

    avg_rating = compute_avg_rating(reviews)
    reviews_count = len(reviews)

    # LOG opcional para ver el conteo en consola
    log.info(f"[public_store] slug={slug} vendor_id={user.id} reviews_count={reviews_count}")

    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "branding": branding,
        "vendor": user,
        "products": products,
        "theme": theme,
        "reviews": reviews,
        "avg_rating": avg_rating,
        "reviews_count": reviews_count,
        
    })

# --------------------------
# Form "Editar mi página"
# --------------------------

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

# --------------------------
# Guardar cambios del branding
# --------------------------

@router.post("/vendor/brand")
async def brand_save(
    request: Request,
    session: Session = Depends(get_session),
    display_name: str = Form(...),
    logo: UploadFile | None = File(None),

    tagline: str | None = Form(None),        
    whatsapp: str | None = Form(None),       
    instagram: str | None = Form(None),      
    location: str | None = Form(None),       
    slug: str | None = Form(None),           
):
    owner_id = _current_owner_id(request)
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.owner_id == owner_id)
    ).first()

    if not branding:
        # crea si no existe
        user = session.exec(select(User).where(User.id == owner_id)).first()
        base_slug = (user.slug if user and user.slug else f"tienda-{owner_id}")
        branding = VendorBranding(
            owner_id=owner_id,
            slug=_unique_slug(session, base_slug),  # CHG: usa helper de slug único
            display_name=display_name.strip(),
            settings=deepcopy(DEFAULT_BRANDING_SETTINGS),  # CHG: arranca con defaults
        )
        session.add(branding)
        session.commit()
        session.refresh(branding)

    # CHG: Normaliza/asegura el dict de settings (evita None o tipos raros)
    settings = ensure_settings_dict(branding.settings)

     # Actualiza nombre visible
    branding.display_name = display_name.strip()
    branding.updated_at = datetime.utcnow()

    # CHG: Si el usuario propuso cambiar el slug, lo normalizamos y garantizamos unicidad
    if slug is not None:
        wanted = _slugify(slug)  # limpia: minúsculas, ascii, guiones
        if wanted and wanted != branding.slug:
            branding.slug = _unique_slug(session, wanted)  # no colisiona con otros VendorBranding

    # CHG: Guardar tagline / whatsapp / instagram / location en settings
    #      (el HTML usa 'tagline', 'whatsapp', 'instagram', 'location')
    #      Si quieres permitir borrar (string vacío), guardamos tal cual lo que venga.
    if tagline is not None:
        settings["tagline"] = tagline.strip()
    if whatsapp is not None:
        settings["whatsapp"] = norm_whatsapp(whatsapp) if whatsapp.strip() else ""  # normaliza o limpia
    if instagram is not None:
        settings["instagram"] = norm_instagram(instagram) if instagram.strip() else ""
    if location is not None:
        settings["location"] = location.strip()

    if logo and getattr(logo, "filename", ""):
        content = await logo.read()
        if not content:
            raise HTTPException(status_code=400, detail="Logo vacío")
        # Guarda en volumen y persiste la URL pública en settings.logo_url
        public_url = save_vendor_bytes(branding.slug, content, logo.filename)
        settings["logo_url"] = public_url
    
    # CHG: Persistimos los settings actualizados
    branding.settings = settings

    session.add(branding); 
    session.commit(); 
    session.refresh(branding)
    
    return RedirectResponse("/vendor/brand?ok=1", status_code=302)

@router.post("/u/{slug}/review")
async def public_create_review(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    rating: int = Form(...),
    comment: str = Form(...),
    website: str = Form("", description="Honeypot field"),  # CHG: campo oculto anti-spam
):
    """
    Crea una review pública para un vendor identificado por slug.
    - No requiere login.
    - Usa un campo 'website' como honeypot anti-spam (debe venir vacío).
    - Por defecto, las reviews quedan is_approved=False (moderación).
    """

    # Honeypot simple: si 'website' viene relleno, asumimos bot y no guardamos nada.
    if website:
        # Opcional: redirigimos como si nada hubiera pasado, para no dar pistas al bot.
        return RedirectResponse(f"/u/{slug}?review=ok", status_code=302)

    # Resolver vendor a partir del slug
    user, branding = resolve_store(session, slug)

    # Validar rating
    if rating < 1 or rating > 5:
        raise HTTPException(status_code=400, detail="Invalid rating")

    name = name.strip() or "Anonymous"
    comment = comment.strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Empty comment")

    review = Review(
        vendor_id=user.id,
        name=name,
        rating=rating,
        comment=comment,
        is_approved=False,   # moderación por defecto
        source="internal",
    )
    session.add(review)
    session.commit()

    return RedirectResponse(f"/u/{slug}?review=ok", status_code=302)


# Panel de reviews para el vendor

@router.get("/admin/{slug}/reviews", response_class=HTMLResponse)
def vendor_reviews_page(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Lista las reviews de un vendor en su panel admin.
    Solo el propio vendor puede verlas.
    """
    vendor = _require_vendor_own(request, session, slug)
    if not vendor:
        return RedirectResponse("/login", status_code=302)

    reviews = session.exec(
        select(Review)
        .where(Review.vendor_id == vendor.id)
        .order_by(Review.created_at.desc())
    ).all()

    return templates.TemplateResponse("admin/vendor_reviews.html", {
        "request": request,
        "vendor": vendor,
        "reviews": reviews,
    })


@router.post("/admin/{slug}/reviews/{review_id}/approve")
def vendor_review_approve(
    slug: str,
    review_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Marca una review como aprobada (visible públicamente).
    """
    vendor = _require_vendor_own(request, session, slug)
    if not vendor:
        return RedirectResponse("/login", status_code=302)

    review = session.get(Review, review_id)
    if not review or review.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_approved = True
    session.add(review)
    session.commit()

    return RedirectResponse(f"/admin/{slug}/reviews", status_code=302)


@router.post("/admin/{slug}/reviews/{review_id}/hide")
def vendor_review_hide(
    slug: str,
    review_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Marca una review como no aprobada (oculta del público).
    """
    vendor = _require_vendor_own(request, session, slug)
    if not vendor:
        return RedirectResponse("/login", status_code=302)

    review = session.get(Review, review_id)
    if not review or review.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Review not found")

    review.is_approved = False
    session.add(review)
    session.commit()

    return RedirectResponse(f"/admin/{slug}/reviews", status_code=302)