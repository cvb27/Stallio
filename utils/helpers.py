
# ------------------------------------------------------------
# Helpers centralizados:
# - Sesión/roles (is_admin, owner_id)
# - Fechas (iso_dt)
# - Autorización por vendor (ensure_vendor_access)
# - Filtros por vendor:
#     * build_order_vendor_condition(...) -> usa columnas en Order si existen
#     * build_vendor_chain_condition(...) -> si Order no tiene vendor, usa Product
# - Query de despachos acotado por scope
# ------------------------------------------------------------

from typing import Optional
from fastapi import Request, HTTPException
from sqlmodel import select, SQLModel, Session
from sqlalchemy.sql.elements import BinaryExpression
from datetime import timezone

# ============ Sesión / roles ============

def is_admin(request: Request) -> bool:
    """True si la sesión tiene admin_email."""
    return "admin_email" in request.session

def owner_id(request: Request) -> Optional[int]:
    """Devuelve el user_id (vendor logueado) o None."""
    uid = request.session.get("user_id")
    return int(uid) if uid is not None else None

# ============ Fechas ============

def iso_dt(dt):
    """Devuelve dt en ISO-8601. Si está naïve, asume UTC."""
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# ============ Vendors / autorización ============

def get_vendor_by_slug(session: Session, UserModel: SQLModel | type, slug: str):
    """Obtiene el vendor por slug o None."""
    return session.exec(select(UserModel).where(UserModel.slug == slug)).first()

def ensure_vendor_access(request: Request, session: Session, slug: str, UserModel=None):
    """
    Verifica que el usuario logueado sea el dueño del slug.
    - Lanza 403 si no hay sesión o si el user_id no coincide.
    - Devuelve el objeto vendor si todo ok.
    """
    uid = owner_id(request)
    if not uid:
        raise HTTPException(status_code=403, detail="No autorizado (sin sesión)")

    from models import User as DefaultUser  # import local para evitar ciclos
    UserModel = UserModel or DefaultUser

    vendor = get_vendor_by_slug(session, UserModel, slug)
    if not vendor or int(vendor.id) != int(uid):
        raise HTTPException(status_code=403, detail="No autorizado")
    return vendor

# ============ Utilidades de tabla/columnas ============

def _table_has_col(Model, name: str) -> bool:
    """True si la columna existe en la tabla del modelo."""
    return hasattr(Model, "__table__") and name in Model.__table__.c

def _col(Model, name: str):
    """Columna SQLAlchemy segura por nombre, sin acceder a atributos de clase."""
    return Model.__table__.c[name]

# ============ Filtros por vendor ============

def build_order_vendor_condition(
    OrderModel,
    *,
    vendor=None,
    user_id: Optional[int] = None
) -> BinaryExpression:
    """
    Construye una condición usando SOLO columnas de Order si existen.
    - IDs preferidos: vendor_id, owner_id, user_id
    - Fallback slugs: vendor_slug, owner_slug
    Lanza ValueError si Order no tiene ninguna columna de vendor.
    """
    # 1) IDs
    for name in ("vendor_id", "owner_id", "user_id"):
        if _table_has_col(OrderModel, name):
            vid = getattr(vendor, "id", None) if vendor is not None else user_id
            if vid is None:
                raise ValueError(f"Se requiere vendor.id o user_id para filtrar por {name}")
            return _col(OrderModel, name) == int(vid)

    # 2) Slugs
    for name in ("vendor_slug", "owner_slug"):
        if _table_has_col(OrderModel, name):
            vslug = getattr(vendor, "slug", None)
            if not vslug:
                raise ValueError(f"Se requiere vendor.slug para filtrar por {name}")
            return _col(OrderModel, name) == vslug

    # 3) No hay columnas en Order
    raise ValueError(
        "No se encontró ninguna columna de vendor en Order "
        "(esperaba vendor_id/owner_id/user_id o vendor_slug/owner_slug)."
    )

def build_vendor_chain_condition(
    OrderModel, OrderItemModel, ProductModel,
    *,
    vendor=None,
    user_id: Optional[int] = None
) -> BinaryExpression:
    """
    Construye una condición para filtrar órdenes del vendor, usando:
      1) Columnas en Order (si existen)
      2) Si NO existen en Order, usa columnas en Product (vía join con OrderItem)
         IDs preferidos: vendor_id, owner_id, user_id
         Fallback slugs: vendor_slug, owner_slug
    Requiere que el SELECT incluya joins a OrderItem y Product si cae en (2).
    """

    # Primero intentamos por Order (si tiene columnas de vendor)
    try:
        return build_order_vendor_condition(OrderModel, vendor=vendor, user_id=user_id)
    except ValueError:
        pass  # Seguimos con Product

    # Intento por columnas en Product
    for name in ("vendor_id", "owner_id", "user_id"):
        if _table_has_col(ProductModel, name):
            vid = getattr(vendor, "id", None) if vendor is not None else user_id
            if vid is None:
                raise ValueError(f"Se requiere vendor.id o user_id para filtrar por Product.{name}")
            return _col(ProductModel, name) == int(vid)

    for name in ("vendor_slug", "owner_slug"):
        if _table_has_col(ProductModel, name):
            vslug = getattr(vendor, "slug", None)
            if not vslug:
                raise ValueError(f"Se requiere vendor.slug para filtrar por Product.{name}")
            return _col(ProductModel, name) == vslug

    # No hay forma de filtrar
    raise ValueError(
        "No se encontró ninguna columna de vendor en Order ni en Product "
        "(esperaba *_id o *_slug)."
    )

# ============ Despachos por scope ============

def build_scope_dispatched_query(
    DispatchedModel,
    *,
    is_admin: bool = False,
    user_id: Optional[int] = None,
    vendor_id: Optional[int] = None
):
    """
    Devuelve select(DispatchedModel) acotado al scope:
      - Admin: sin filtro por owner_id.
      - Vendor: owner_id = vendor_id o user_id.
    """
    from sqlmodel import select  # import local por compatibilidad
    q = select(DispatchedModel)
    if is_admin:
        return q

    vid = vendor_id or user_id
    if vid is None:
        return q.where(DispatchedModel.owner_id == -1)  # seguro: no devuelve nada
    return q.where(DispatchedModel.owner_id == int(vid))
