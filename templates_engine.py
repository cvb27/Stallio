"""
Punto único para crear y configurar la instancia global de Jinja2Templates.

Objetivo:
- Evitar tener múltiples `Jinja2Templates(directory="templates")` repartidos.
- Inyectar helpers globales (como `t` para traducciones y `locale`) en TODAS las plantillas.
- Que todos los routers usen la misma instancia: `from templates_engine import templates`.
"""

from fastapi.templating import Jinja2Templates

# Importamos el helper de traducciones y el locale por defecto.

from utils.i18n import t, DEFAULT_LOCALE

# ==============
# Instancia única
# ==============

# Esta es la ÚNICA instancia de Jinja2Templates que debes usar en todo el proyecto.
# En cada router:
#   from templates_engine import templates
templates = Jinja2Templates(directory="templates")

# ============================
# Helpers globales para Jinja2
# ============================

# `t`: función de traducción.
# Podrás usarla en cualquier plantilla:
#   {{ t("brand.edit_title", locale) }}
templates.env.globals["t"] = t

# `locale`: idioma actual (por ahora fijo en DEFAULT_LOCALE).
# En las plantillas:
#   {{ locale }}  -> "en"
templates.env.globals["locale"] = DEFAULT_LOCALE


# =====================================
# (Opcional) Hook para futura multilengua
# =====================================
# Si en el futuro quieres que el idioma dependa de la request (cookie, sesión, query string),
# puedes:
#
# 1) Añadir un middleware en main.py que ponga `request.state.locale`.
# 2) Exponer una pequeña función global que lea ese valor.
#
# Ejemplo (cuando lo necesites):
#
#   def get_locale_from_request(request):
#       return getattr(request.state, "locale", DEFAULT_LOCALE)
#
#   templates.env.globals["get_locale"] = get_locale_from_request
#
# Y en las plantillas:
#   {{ t("brand.edit_title", get_locale(request)) }}
#
# Por ahora, lo dejamos simple y fijo en inglés.
