from fastapi import APIRouter, Request, Form, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select
from models import Product, PaymentReport, User, VendorBranding
from db import get_session
from notify import ws_manager
from sms import send_sms
from config import PAYMENT_INFO, SELLER_MOBILE
from routers.store_helpers import resolve_store, build_theme
import secrets, asyncio, json

DEFAULT_IMAGE_URL = "/static/img/product_placeholder.png"

router = APIRouter(prefix="", tags=["Public"])
templates = Jinja2Templates(directory="templates")

def _get_user_by_slug(session: Session, slug: str) -> User:
    user = session.exec(select(User).where(User.slug == slug)).first()
    if not user: raise HTTPException(status_code=404, detail="Vendedor no encontrado")
    return user

# ---------- HOME MASTER ----------
@router.get("/", include_in_schema=False)
def root_redirect():
     return RedirectResponse("/login", status_code=302)


# ---------- HOME PÚBLICO ----------
@router.get("/public", name="public_home", response_class=HTMLResponse)
async def public_home(request: Request, session: Session = Depends(get_session)):
    products = session.exec(
        select(Product).order_by(Product.id.desc())
    ).all()
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "products": products
    })
    

@router.get("/u/{slug}")
def public_store(slug: str, request: Request, session: Session = Depends(get_session)):
    user = _get_user_by_slug(session, slug)
    branding = session.exec(select(VendorBranding).where(VendorBranding.owner_id == user.id)).first()
    products = session.exec(select(Product).where(Product.owner_id == user.id)).all()
    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "vendor": user,
        "branding": branding,
        "products": products,  # cada p.image_url ya es /uploads/...
    })

# JSON para la grilla pública del vendor

@router.get("/u/{slug}/products.json")
def public_products_json(slug: str, session: Session = Depends(get_session)):
    user = _get_user_by_slug(session, slug)
    rows = session.exec(select(Product).where(Product.owner_id == user.id)).all()
    return [{
        "id": p.id, "name": p.name, "price": p.price, "stock": p.stock,
        "image_url": p.image_url,  # /uploads/...
    } for p in rows]


@router.get("/public/payment-info")
def payment_info():
    return PAYMENT_INFO

# ---------- WEBSOCKET COMPARTIDO (público y admin escuchan aquí) ----------
@router.websocket("/ws/public")
async def ws_public(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # si quieres recibir pings del cliente, léelos aquí
        while True:
            await ws.receive_text()  # o ws.receive_json(); también puedes omitir si no envías nada
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(ws)


# ---------- REPORTE DE PAGO (desde el modal del público) ----------
@router.post("/u/{slug}/report-payment")
async def public_report_payment(
    slug: str,
    product_id: int = Form(...),
    qty: int = Form(...),
    amount_type: str = Form(...),       # "50" o "100"
    payer_name: str = Form(""),
    phone: str = Form(""),
    session: Session = Depends(get_session),
):
    # 1) Resolver tienda por slug (branding o user), fuente de verdad
    user, branding = resolve_store(session, slug)

    # 2) Producto y pertenencia
    product = session.get(Product, product_id)
    if not product or product.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Producto inválido")

    # 3) Normalizaciones
    try:
        qty = max(1, int(qty))
    except Exception:
        qty = 1
    amount_type = "50" if amount_type == "50" else "100"

    # 4) Calcular monto
    factor = 0.5 if amount_type == "50" else 1.0
    amount = round(float(product.price or 0.0) * qty * factor, 2)

    # 5) Crear reporte con owner correcto
    report = PaymentReport(
        product_id=product.id,
        qty=qty,
        payer_name=payer_name or None,
        phone=phone or None,
        amount_type=amount_type,
        amount=amount,
        owner_id=user.id,
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    # 6) Notificar dashboards por WebSocket
    payload = {
        "type": "payment_reported",
        "report": {
            "id": report.id,
            "product_id": product.id,
            "product_name": product.name,
            "qty": report.qty,
            "amount_type": report.amount_type,   # "50" o "100"
            "amount": report.amount,
            "payer_name": report.payer_name or "",
            "phone": report.phone or "",
            "created_at": report.created_at.isoformat(),
        }
    }
    try:
        asyncio.create_task(ws_manager.broadcast(json.dumps(payload)))
    except Exception:
        pass

    # 7) (Opcional) SMS al vendedor
    if SELLER_MOBILE and send_sms:
        body = f"Pago reportado: {payer_name or 'Cliente'} · {qty} x {product.name} · {amount_type}% · ${amount:.2f}"
        try:
            send_sms(SELLER_MOBILE, body)
        except Exception:
            pass

    # 8) Respuesta JSON explícita
    return JSONResponse({"ok": True, "report_id": report.id, "amount": amount})


# ---------- DASHBOARD ADMIN: ÓRDENES ----------
@router.post("/pago/{ref}/notificar", response_class=HTMLResponse)
def notify_payment(
    request: Request,
    ref: str,
    amount: float = Form(...),
    method: str = Form("ZELLE"),
    reference: str = Form(""),
    buyer_email: str = Form(""),
    buyer_phone: str = Form(""),
    is_full: int = Form(0)       # 1 si marca pago total
):
    
    # 👇 import diferido: evita ciclos de import
    from notify import send_email, send_sms

    with get_session() as con:
        order = con.execute(
            """SELECT o.ref, o.total_amount, o.vendor_id, p.name product_name,
                      v.name vendor_name, v.email vendor_email, v.phone vendor_phone
               FROM orders o
               JOIN products p ON p.id=o.product_id
               JOIN vendors v  ON v.id=o.vendor_id
               WHERE o.ref=?""", (ref,)
        ).fetchone()
        if not order:
            return RedirectResponse("/", status_code=302)

        con.execute(
            """INSERT INTO payment_reports
               (order_ref, amount, method, reference, buyer_email, buyer_phone, is_full, status)
               VALUES (?,?,?,?,?,?,?, 'reportado')""",
            (ref, amount, method, reference, buyer_email, buyer_phone, 1 if is_full else 0)
        )


