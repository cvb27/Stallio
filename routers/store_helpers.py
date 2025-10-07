from sqlmodel import select, desc
from fastapi import HTTPException
from models import User, VendorBranding, DEFAULT_BRANDING_SETTINGS
from copy import deepcopy
import re

def get_branding_by_owner(session, owner_id):
    # toma SIEMPRE el más reciente por si quedaron duplicados
    return session.exec(
        select(VendorBranding)
        .where(VendorBranding.owner_id == owner_id)
        .order_by(desc(VendorBranding.updated_at), desc(VendorBranding.id))
        
    ).first()

def resolve_store(session, slug: str):
    """
    Fuente de verdad: busca primero por VendorBranding.slug; si no, por User.slug.
    Devuelve (user, branding) o 404.
    """
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.slug == slug)
    ).first()
    if branding:
        user = session.exec(select(User).where(User.id == branding.owner_id)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Vendedor no encontrado")
    else:
        user = session.exec(select(User).where(User.slug == slug)).first()
        if not user:
            raise HTTPException(status_code=404, detail="Vendedor no encontrado")
        branding = get_branding_by_owner(session, user.id)
    return user, branding

def ensure_settings_dict(settings):
    base = deepcopy(DEFAULT_BRANDING_SETTINGS)
    if isinstance(settings, dict):
        base.update(settings)
    return base

def norm_whatsapp(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\d+]", "", s)     # deja dígitos y +
    if s.startswith("00"):           # 0034 -> +34
        s = "+" + s[2:]
    return s

def norm_instagram(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("https://www.instagram.com/", "").replace("http://www.instagram.com/", "")
    s = s.replace("https://instagram.com/", "").replace("http://instagram.com/", "")
    s = s.replace("instagram.com/", "")
    s = s.strip("/").lstrip("@")
    return s

def build_theme(branding):
    """
    Devuelve un dict con los datos de marca para las vistas públicas.
    Normaliza logo_url para que, si viene de /static/uploads, apunte a /uploads.
    """

    s = ensure_settings_dict(getattr(branding, "settings", None))

    primary = (s.get("primary_color") or "#0f172a").strip()
    accent  = (s.get("accent_color")  or "").strip().lower()
    
    # 1) tomar logo desde settings o atributo plano
    logo_url = s.get("logo_url") or (getattr(branding, "logo_url", None) if branding else None)

    # 2) normalizar rutas antiguas
    if logo_url and logo_url.startswith("/static/uploads/"):
        logo_url = logo_url.replace("/static/uploads/", "/uploads/", 1)

    # 2) fallback absoluto
    if not logo_url:
        logo_url = "/static/public/assets/img/default-store.svg"

    return {

        # Título / tagline
        "title":    (branding.display_name if branding else "Mi Tienda"),
        "tagline":  s.get("tagline") or "La mejor selección para ti",

        # Colores con fallback a defaults globales
        "primary":  s.get("primary_color") or DEFAULT_BRANDING_SETTINGS["primary_color"],
        "accent":   s.get("accent_color")  or DEFAULT_BRANDING_SETTINGS["accent_color"],

        # Contacto normalizado
        "wa":       norm_whatsapp(s.get("whatsapp","")),
        "ig":       norm_instagram(s.get("instagram","")),

        # Medios
        "hero": s.get("hero_image_url", ""),
        "logo": logo_url,
        
    }