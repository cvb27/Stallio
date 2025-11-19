
"""
utils/i18n.py

Mini-sistema de traducciones muy simple.

- Por ahora solo usamos inglés ("en").
- La función principal es `t(key, locale="en")`.
- Si no se encuentra la clave en el catálogo, se devuelve la propia clave.
"""

from typing import Dict

# Idioma por defecto de la app
DEFAULT_LOCALE = "en"

CATALOG: Dict[str, Dict[str, str]] = {
    "en": {
        "brand.edit_title": "Edit my page",
        "brand.view_public": "View public page",
        "brand.copy_url": "Copy URL",
        "brand.copied": "Copied",
        "brand.save_ok": "Changes saved successfully.",
        "brand.save_err": "Something went wrong. Please try again.",
        "brand.basic_data": "Basic data",
        "brand.display_name": "Display name",
        "brand.tagline": "Tagline (Optional)",
        "brand.whatsapp": "WhatsApp (Optional)",
        "brand.instagram": "Instagram (Optional)",
        "brand.location": "Location (Optional)",
        "brand.slug": "Slug (Optional) (short URL)",
        "brand.logo": "Logo (PNG/JPG/WEBP) (Optional)",
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.public_url": "Public URL:",
        "cart.title": "Cart",
        "cart.added": "Item added to cart",
        "cart.empty": "Your cart is empty.",
        # ...agrega las demás etiquetas que uses
    },
    # si mañana agregas 'es': {...}
}

def t(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """
    Devuelve el texto traducido para una clave dada y un idioma dado.

    - Si el idioma no existe, usa DEFAULT_LOCALE.
    - Si la clave no existe en el idioma, devuelve la propia clave (para que al menos se vea algo).

    Uso típico en plantillas:
        {{ t("brand.edit_title", locale) }}
    """
    lang_catalog = CATALOG.get(locale) or CATALOG.get(DEFAULT_LOCALE, {})
    return lang_catalog.get(key, key)