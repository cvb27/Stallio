
# ------------------------------------------------------------
# - Toda la lógica repetida (is_admin, owner_id, iso, filtros por vendor)
#   vive en utils/helpers.py para mantener ordenado y DRY.

# - Evitamos depender estrictamente de Order.vendor_id: si tu esquema usa
#   vendor_slug, el helper lo detecta y aplica el filtro correcto.

# - Rutas sin colisiones: "/{slug}/orders" (vendor) y "/orders/all" (admin).
# ------------------------------------------------------------

from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from models import PaymentReport, Product, DispatchedOrder, User, Order, OrderItem
from notify import ws_manager
from db import get_session
from collections import defaultdict

# ✅ Helpers centralizados
from utils.helpers import (
    is_admin,
    owner_id,
    iso_dt,
    ensure_vendor_access,
    build_vendor_chain_condition,
    build_scope_dispatched_query,
)

router = APIRouter(prefix="/admin", tags=["Admin Orders"])
templates = Jinja2Templates(directory="templates")

# =========================
# Landing de /admin/orders
# =========================

"""
    Redirecciones:
    - Admin → /master/users (tu master dashboard).
    - Vendor → /admin/{slug}/orders (dashboard del vendor).
    - Sin sesión → /login.
    """

@router.get("/orders", response_class=HTMLResponse)
async def dashboard_page(request: Request, session: Session = Depends(get_session)):

    # Si es admin, redirige al master dashboard.
    if is_admin(request):
        return RedirectResponse("/master/users", status_code=302)
    
    # Si es vendor redirige al dashboard vendor (usa productos como “home”)
    uid = owner_id(request)
    if uid:
        vendor = session.get(User, int(uid))
        if vendor:
            return RedirectResponse(f"/admin/{vendor.slug}/orders", status_code=302)

    return RedirectResponse("/login", status_code=302)

# =====================================
# Dashboard de órdenes para un vendor
# =====================================

"""
    Muestra las órdenes relacionadas a UN vendor (el dueño del slug).
    Cambios CLAVE:
    - Autorización centralizada en ensure_vendor_access (lanza 403 si no es dueño).
    - Filtro por vendor dinámico (id o slug) con build_order_vendor_condition.
    - Ya NO usamos PaymentReport.product_id (no existe).
    - Encadenamos: PaymentReport -> Order -> OrderItem -> Product.
    - Agrupación por PaymentReport.id para manejar órdenes con múltiples items.
    """

@router.get("/{slug}/orders", response_class=HTMLResponse)
async def vendor_dashboard(slug: str, request: Request, session: Session = Depends(get_session)):

    vendor = ensure_vendor_access(request, session, slug)  # ✅ 403 si no es el dueño

    cond = build_vendor_chain_condition(Order, OrderItem, Product, vendor=vendor)  # ⬅️ clave

    rows = session.exec(
        select(PaymentReport, Order, OrderItem, Product)
        .join(Order, Order.id == PaymentReport.order_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(cond)
        .order_by(PaymentReport.id.desc())
    ).all()

    # Agrupación por reporte
    grouped = defaultdict(lambda: {
        "id": None,
        "order_id": None,
        "items": [],
        "amount": 0.0,
        "payer_name": "",
        "method": "",
        "reference": "",
        "notes": "",
        "created_at": None,
    })

    for pr, order, item, prod in rows:
        g = grouped[pr.id]
        if g["id"] is None:
            g["id"] = pr.id
            g["order_id"] = order.id
            g["amount"] = getattr(pr, "amount", 0.0)
            g["payer_name"] = getattr(pr, "payer_name", "") or ""
            g["method"] = getattr(pr, "method", "") or ""
            g["reference"] = getattr(pr, "reference", "") or ""
            g["notes"] = getattr(pr, "notes", "") or ""
            g["created_at"] = iso_dt(getattr(pr, "created_at", None))
        g["items"].append({
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": item.qty,
            "unit_price": item.unit_price,
        })

    # Despachadas del vendor (scope correcto)
    disp_map = {
        d.payment_report_id: d.created_at
        for d in session.exec(
            build_scope_dispatched_query(DispatchedOrder, vendor_id=vendor.id)
        ).all()
    }

    pendientes, despachadas = [], []
    for report_id, data in grouped.items():
        payload = {
            **data,
            "created_at": data["created_at"],
        }
        if report_id in disp_map:
            payload["dispatched_at"] = iso_dt(disp_map[report_id])
            despachadas.append(payload)
        else:
            pendientes.append(payload)

    return templates.TemplateResponse(
        "admin/orders.html",
        {
            "request": request,
            "orders": pendientes,       # no despachadas
            "dispatched": despachadas,  # ya despachadas
            "vendor": vendor
        }
    )

# =========================
# Pagos (lista general)
# =========================

"""
    Lista de PaymentReports.
    - Admin ve todos.
    - Vendor ve solo los suyos (vía join con Order.vendor_id).
    """

@router.get("/admin/payments", response_class=HTMLResponse)
async def admin_payments(request: Request, session: Session = Depends(get_session)):

    base = (
        select(PaymentReport, Order)
        .join(Order, Order.id == PaymentReport.order_id)
    )

    if not is_admin(request):
        uid = owner_id(request)
        if not uid:
            return RedirectResponse("/login", status_code=302)
        
        # Condición dinámica según tu esquema
        vendor = session.get(User, int(uid))
        base = (base
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(Product, Product.id == OrderItem.product_id)
        )
        cond = build_vendor_chain_condition(Order, OrderItem, Product, vendor=vendor)
        base = base.where(cond)

    rows = session.exec(
        base.order_by(PaymentReport.id.desc()).group_by(PaymentReport.id, Order.id)  # ⬅️ evita duplicados
    ).all()

    # Adaptación a lo que tu template espera
    reports = [{
        "id": pr.id,
        "order_id": order.id,
        "amount": getattr(pr, "amount", 0.0),
        "payer_name": getattr(pr, "payer_name", "") or "",
        "method": getattr(pr, "method", "") or "",
        "reference": getattr(pr, "reference", "") or "",
        "notes": getattr(pr, "notes", "") or "",
        "created_at": iso_dt(getattr(pr, "created_at", None)),
    } for pr, order in rows]

    return templates.TemplateResponse(
        "admin/payments.html",
        {"request": request, "reports": reports}
    )


# ============================================
# Versión "admin_orders" (dashboard compacto)
# ============================================

"""
    Dashboard compacto de órdenes:
    PaymentReport -> Order -> OrderItem -> Product.
    - Agrupamos por report_id para manejar órdenes con múltiples items.
    """

@router.get("/admin/orders", name="admin_orders", response_class=HTMLResponse)
def admin_orders_page(request: Request, session: Session = Depends(get_session)):

    base = (
        select(PaymentReport, Order, OrderItem, Product)
        .join(Order, Order.id == PaymentReport.order_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .order_by(PaymentReport.id.desc())
    )

    if not is_admin(request):
        uid = owner_id(request)
        if not uid:
            return RedirectResponse("/login", status_code=302)
        vendor = session.get(User, int(uid))
        cond = build_vendor_chain_condition(Order, OrderItem, Product, vendor=vendor)  # ⬅️ clave
        base = base.where(cond)

    rows = session.exec(base).all()

    grouped = defaultdict(lambda: {"items": []})
    for pr, order, item, prod in rows:
        g = grouped[pr.id]
        if "id" not in g:
            g["id"] = pr.id
            g["order_id"] = order.id
            g["amount"] = getattr(pr, "amount", 0.0)
            g["payer_name"] = getattr(pr, "payer_name", "") or ""
            g["method"] = getattr(pr, "method", "") or ""
            g["reference"] = getattr(pr, "reference", "") or ""
            g["notes"] = getattr(pr, "notes", "") or ""
            g["created_at"] = iso_dt(getattr(pr, "created_at", None))
        g["items"].append({
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": item.qty,
            "unit_price": item.unit_price,
        })

    # dispatched del scope correcto
    disp_q = build_scope_dispatched_query(DispatchedOrder, is_admin=is_admin(request), user_id=owner_id(request))
    disp_map = {d.payment_report_id: d.created_at for d in session.exec(disp_q).all()}

    pendientes, despachadas = [], []
    for rid, data in grouped.items():
        row = {**data, "dispatched_at": iso_dt(disp_map.get(rid))}
        if rid in disp_map:
            despachadas.append(row)
        else:
            pendientes.append(row)

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "orders": pendientes, "dispatched": despachadas}
    )

# =========================
# JSON: pendientes
# =========================

    """
    Devuelve en JSON las órdenes no despachadas.
    - Filtrado por vendor via Order.vendor_id.
    - Agrupación por reporte para soportar órdenes con múltiples items.
    """

@router.get("/orders/list.json")
def admin_orders_json(request: Request, session: Session = Depends(get_session)):
    base = (
        select(PaymentReport, Order, OrderItem, Product)
        .join(Order, Order.id == PaymentReport.order_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .order_by(PaymentReport.id.desc())
    )

    if not is_admin(request):
        uid = owner_id(request)
        if not uid:
            raise HTTPException(status_code=401, detail="No autenticado")
        vendor = session.get(User, int(uid))
        cond = build_vendor_chain_condition(Order, OrderItem, Product, vendor=vendor)  # ⬅️ clave        
        base = base.where(cond)

    rows = session.exec(base).all()

    # dispatched ids del scope correspondiente
    disp_q = build_scope_dispatched_query(DispatchedOrder, is_admin=is_admin(request), user_id=owner_id(request))
    dispatched_ids = {d.payment_report_id for d in session.exec(disp_q).all()}

    grouped = defaultdict(lambda: {"items": []})
    for pr, order, item, prod in rows:
        if pr.id in dispatched_ids:
            continue  # solo pendientes
        g = grouped[pr.id]
        if "id" not in g:
            g["id"] = pr.id
            g["order_id"] = order.id
            g["amount"] = getattr(pr, "amount", 0.0)
            g["payer_name"] = getattr(pr, "payer_name", "") or ""
            g["method"] = getattr(pr, "method", "") or ""
            g["reference"] = getattr(pr, "reference", "") or ""
            g["notes"] = getattr(pr, "notes", "") or ""
            g["created_at"] = iso_dt(getattr(pr, "created_at", None))
        g["items"].append({
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": item.qty,
            "unit_price": item.unit_price,
        })

    # salida
    return [{
        "id": data["id"],
        "order_id": data["order_id"],
        "items": data["items"],
        "amount": data["amount"],
        "payer_name": data["payer_name"],
        "method": data["method"],
        "reference": data["reference"],
        "notes": data["notes"],
        "created_at": data["created_at"],
    } for _, data in grouped.items()]

# =========================
# JSON: despachadas
# =========================

    """
    Devuelve en JSON las órdenes despachadas.
    - Igual estrategia de joins y agrupación.
    """

@router.get("/orders/dispatched.json")
def admin_orders_dispatched_json(request: Request, session: Session = Depends(get_session)):
    base = (
        select(PaymentReport, Order, OrderItem, Product)
        .join(Order, Order.id == PaymentReport.order_id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .order_by(PaymentReport.id.desc())
    )

    if not is_admin(request):
        uid = owner_id(request)
        if not uid:
            raise HTTPException(status_code=401, detail="No autenticado")
        vendor = session.get(User, int(uid))
        cond = build_vendor_chain_condition(Order, OrderItem, Product, vendor=vendor)  # ⬅️ clave
        base = base.where(cond)

    rows = session.exec(base).all()

    disp_q = build_scope_dispatched_query(DispatchedOrder, is_admin=is_admin(request), user_id=owner_id(request))
    dispatched = {d.payment_report_id: d.created_at for d in session.exec(disp_q).all()}

    grouped = defaultdict(lambda: {"items": []})
    for pr, order, item, prod in rows:
        if pr.id not in dispatched:
            continue  # solo despachadas
        g = grouped[pr.id]
        if "id" not in g:
            g["id"] = pr.id
            g["order_id"] = order.id
            g["amount"] = getattr(pr, "amount", 0.0)
            g["payer_name"] = getattr(pr, "payer_name", "") or ""
            g["method"] = getattr(pr, "method", "") or ""
            g["reference"] = getattr(pr, "reference", "") or ""
            g["notes"] = getattr(pr, "notes", "") or ""
            g["created_at"] = iso_dt(getattr(pr, "created_at", None))
            g["dispatched_at"] = iso_dt(dispatched[pr.id])
        g["items"].append({
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": item.qty,
            "unit_price": item.unit_price,
        })

    return [{
        "id": data["id"],
        "order_id": data["order_id"],
        "items": data["items"],
        "amount": data["amount"],
        "payer_name": data["payer_name"],
        "method": data["method"],
        "reference": data["reference"],
        "notes": data["notes"],
        "created_at": data["created_at"],
        "dispatched_at": data.get("dispatched_at"),
    } for _, data in grouped.items()]

# =========================
# Acción: marcar como despachado
# =========================

    """
    Marca un PaymentReport como despachado (idempotente).
    - Admin o vendor dueño de la orden.
    - Guarda DispatchedOrder(payment_report_id, owner_id).
    - Emite evento por WebSocket.
    """

@router.post("/orders/dispatch/{report_id}")
def dispatch_order(
    report_id: int, 
    request: Request, 
    session: Session = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    # Permitir admin o vendor autenticado
    
    admin = is_admin(request)
    uid = owner_id(request)
    if not admin and not uid:
        raise HTTPException(status_code=401, detail="No autenticado")

    pr = session.get(PaymentReport, report_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    order = session.get(Order, pr.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada (Order)")

    owner_for_dispatch = None
    # 1) Si Order tiene *_id de vendor:
    for name in ("vendor_id", "owner_id", "user_id"):
        if hasattr(Order, "__table__") and name in Order.__table__.c:
            owner_for_dispatch = getattr(order, name, None)
            break

    # 2) Si no, resolvemos por Product (primer item)
    if owner_for_dispatch is None:
        item = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).first()
        if not item:
            raise HTTPException(status_code=400, detail="Orden sin items")
        prod = session.get(Product, item.product_id)
        if not prod:
            raise HTTPException(status_code=400, detail="Producto no encontrado")

        # IDs primero
        for name in ("vendor_id", "owner_id", "user_id"):
            if hasattr(Product, "__table__") and name in Product.__table__.c:
                owner_for_dispatch = getattr(prod, name, None)
                break
        # Slug → id real
        if owner_for_dispatch is None:
            for name in ("vendor_slug", "owner_slug"):
                if hasattr(Product, "__table__") and name in Product.__table__.c:
                    vslug = getattr(prod, name, None)
                    if vslug:
                        vendor = session.exec(select(User).where(User.slug == vslug)).first()
                        owner_for_dispatch = vendor.id if vendor else None
                    break

    if not admin:
        # Asegura que el vendor autenticado es el dueño
        if int(owner_for_dispatch or -1) != int(uid):
            raise HTTPException(status_code=403, detail="No autorizado")

    # Idempotencia
    exists = session.exec(
        select(DispatchedOrder).where(DispatchedOrder.payment_report_id == report_id)
    ).first()
    if exists:
        return {"ok": True, "already": True}

    d = DispatchedOrder(payment_report_id=report_id, owner_id=owner_for_dispatch)
    session.add(d)
    session.commit()
    session.refresh(d)

    payload = {"type": "order_dispatched", "report_id": report_id, "dispatched_at": iso_dt(d.created_at)}
    # Si ws_manager.broadcast requiere JSON string:
    # import json; background_tasks and ws_manager may vary en tu app:
    if background_tasks is not None:
        import json
        background_tasks.add_task(ws_manager.broadcast, json.dumps(payload))

    return {"ok": True, "report_id": report_id, "dispatched_at": iso_dt(d.created_at)}

