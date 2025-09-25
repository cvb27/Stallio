
from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from models import PaymentReport, Product, DispatchedOrder
from notify import ws_manager
from db import get_session
import asyncio, json

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# HELPERS #

def _is_admin(request: Request) -> bool:
    return "admin_email" in request.session

def _owner_id(request: Request):
    return request.session.get("user_id")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, session: Session = Depends(get_session)):
    # Si es admin, redirige al master dashboard.
    if "admin_email" in request.session:
        return RedirectResponse("/master/users", status_code=302)

     # Si es vendor redirige al dashboard vendor (usa productos como “home”)
    if "user_id" in request.session:
        vendor_id = request.session["user_id"]
        from models import User
        vendor = session.get(User, vendor_id)
        if vendor:
            return RedirectResponse(f"/admin/{vendor.slug}/dashboard", status_code=302)

    # Sin sesión válida → login
    return RedirectResponse("/login", status_code=302)
"""
@router.get("/admin/{slug}/orders", response_class=HTMLResponse)
async def vendor_dashboard(slug: str, request: Request, session: Session = Depends(get_session)):
    # Asegúrate que está logueado como vendor
    if "user_id" not in request.session:
        return RedirectResponse("/login", status_code=302)

    from models import User, PaymentReport, Product, DispatchedOrder
    vendor = session.exec(select(User).where(User.slug == slug)).first()
    if not vendor or vendor.id != request.session["user_id"]:
        raise HTTPException(status_code=403, detail="No autorizado")

    # Traer órdenes de ese vendor
    reports = session.exec(
        select(PaymentReport, Product)
        .join(Product, Product.id == PaymentReport.product_id)
        .where(PaymentReport.owner_id == vendor.id)
        .order_by(PaymentReport.id.desc())
    ).all()

    dispatched_map = {
        d.payment_report_id: d.created_at
        for d in session.exec(select(DispatchedOrder).where(DispatchedOrder.owner_id == vendor.id)).all()
    }

    pendientes, despachadas = [], []
    for pr, prod in reports:
        row = {
            "id": pr.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": pr.qty,
            "amount_type": pr.amount_type,
            "amount": pr.amount,
            "payer_name": pr.payer_name or "",
            "phone": pr.phone or "",
            "created_at": pr.created_at,
        }
        if pr.id in dispatched_map:
            row["dispatched_at"] = dispatched_map[pr.id]
            despachadas.append(row)
        else:
            pendientes.append(row)

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "orders": pendientes, "dispatched": despachadas, "vendor": vendor}
    )



@router.get("/admin/payments", response_class=HTMLResponse)
async def admin_payments(request: Request, session: Session = Depends(get_session)):

    # Permitir vendor; admin ve todo, vendor ve solo suyo
    if not _is_admin(request) and not _owner_id(request):
        return RedirectResponse("/login", status_code=302)

    q = select(PaymentReport).order_by(PaymentReport.created_at.desc())
    if not _is_admin(request):
        q = q.where(PaymentReport.owner_id == _owner_id(request))  # solo del vendor

    reports = session.exec(q).all()

    return templates.TemplateResponse(
        "admin/payments.html",
        {"request": request, "reports": reports}
    )
    
@router.get("/admin/orders", name="admin_orders", response_class=HTMLResponse)
def admin_orders_page(request: Request, session: Session = Depends(get_session)):

    # Permitir vendor; admin ve todo
    if not _is_admin(request) and not _owner_id(request):
        return RedirectResponse("/login", status_code=302)

    base = (
        select(PaymentReport, Product)
        .join(Product, Product.id == PaymentReport.product_id)
        .order_by(PaymentReport.id.desc())
    )
    if not _is_admin(request):
        base = base.where(PaymentReport.owner_id == _owner_id(request))  # vendor

    reports = session.exec(base).all()

    # dispatched del scope correcto
    disp_q = select(DispatchedOrder)
    if not _is_admin(request):
        disp_q = disp_q.where(DispatchedOrder.owner_id == _owner_id(request))
    dispatched_map = {
        d.payment_report_id: d.created_at
        for d in session.exec(disp_q).all()
    }

    pendientes = []
    despachadas = []
    for pr, prod in reports:
        row = {
            "id": pr.id,
            "product_id": prod.id,
            "product_name": prod.name,
            "qty": pr.qty,
            "amount_type": pr.amount_type,
            "amount": pr.amount,
            "payer_name": pr.payer_name or "",
            "phone": pr.phone or "",
            "created_at": pr.created_at,
        }
        if pr.id in dispatched_map:
            row["dispatched_at"] = dispatched_map[pr.id]
            despachadas.append(row)
        else:
            pendientes.append(row)

    return templates.TemplateResponse(
        "admin/dashboard.html",   # 👈 usas tu MISMO dashboard.html
        {"request": request, "orders": pendientes, "dispatched": despachadas}
    )

# JSON: pendientes
@router.get("/admin/orders/list.json")
def admin_orders_json(request: Request, session: Session = Depends(get_session)):
    base = (
        select(PaymentReport, Product)
        .join(Product, Product.id == PaymentReport.product_id)
        .order_by(PaymentReport.id.desc())
    )

    # Filtrar para vendedor
    if not _is_admin(request):
        if not _owner_id(request):
            raise HTTPException(status_code=401, detail="No autenticado")
        base = base.where(PaymentReport.owner_id == _owner_id(request))

    reports = session.exec(base).all()

    # dispatched ids del scope correspondiente
    disp_q = select(DispatchedOrder)
    if not _is_admin(request):
        disp_q = disp_q.where(DispatchedOrder.owner_id == _owner_id(request))
    dispatched_ids = {d.payment_report_id for d in session.exec(disp_q).all()}

    
    def _iso(dt):
        if not dt:
            return None
        if dt.tzinfo is None:  # si viene naïve, asumimos UTC
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    return [{
        "id": pr.id,
        "product_id": prod.id,
        "product_name": prod.name,
        "qty": pr.qty,
        "amount_type": pr.amount_type,
        "amount": pr.amount,
        "payer_name": pr.payer_name or "",
        "phone": pr.phone or "",
        "created_at": _iso(pr.created_at),
    } for pr, prod in reports if pr.id not in dispatched_ids]

# JSON: despachadas
@router.get("/admin/orders/dispatched.json")
def admin_orders_dispatched_json(request: Request, session: Session = Depends(get_session)):  # CHANGE: agrega request
    base = (
        select(PaymentReport, Product)
        .join(Product, Product.id == PaymentReport.product_id)
        .order_by(PaymentReport.id.desc())
    )
    if not _is_admin(request):
        if not _owner_id(request):
            raise HTTPException(status_code=401, detail="No autenticado")
        base = base.where(PaymentReport.owner_id == _owner_id(request))

    reports = session.exec(base).all()

    disp_q = select(DispatchedOrder)
    if not _is_admin(request):
        disp_q = disp_q.where(DispatchedOrder.owner_id == _owner_id(request))
    dispatched = {
        d.payment_report_id: d.created_at
        for d in session.exec(disp_q).all()
    }

    def _iso(dt):
        if not dt:
            return None
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    out = []
    for pr, prod in reports:
        if pr.id in dispatched:
            out.append({
                "id": pr.id,
                "product_id": prod.id,
                "product_name": prod.name,
                "qty": pr.qty,
                "amount_type": pr.amount_type,
                "amount": pr.amount,
                "payer_name": pr.payer_name or "",
                "phone": pr.phone or "",
                "created_at": _iso(pr.created_at),
                "dispatched_at": _iso(dispatched[pr.id]),
            })
    return out

# Acción: marcar como despachado
@router.post("/admin/orders/dispatch/{report_id}")
def dispatch_order(
    report_id: int, 
    request: Request, 
    session: Session = Depends(get_session),
    background_tasks: BackgroundTasks = None,
):
    # Permitir admin o vendor autenticado 
    is_admin = "admin_email" in request.session
    user_id  = request.session.get("user_id")
    if not is_admin and not user_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    
    # 1) Obtener el reporte
    pr = session.get(PaymentReport, report_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    
    # 2) Autorización: admin o dueño de la orden
    if not _is_admin(request) and _owner_id(request) != pr.owner_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    #  3) Si ya está despachada, idempotente
    exists = session.exec(
        select(DispatchedOrder).where(DispatchedOrder.payment_report_id == report_id)
    ).first()
    if exists:
        return {"ok": True, "already": True}

    # 4) Crear registro de despacho con owner correcto
    d = DispatchedOrder(
        payment_report_id=report_id,
        owner_id=pr.owner_id,    # 👈 CLAVE para reconocer de que vendor es.
    )
    session.add(d)
    session.commit()
    session.refresh(d)

    # 5) Notificar por WebSocket (opcional)
    payload = {
        "type": "order_dispatched",
        "report_id": report_id,
        "dispatched_at": d.created_at.isoformat(),
    }
    if background_tasks is not None:
        background_tasks.add_task(ws_manager.broadcast, json.dumps(payload))

    return {"ok": True, "report_id": report_id, "dispatched_at": d.created_at.isoformat()}

"""