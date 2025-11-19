from fastapi import APIRouter, Request, Form, Depends, WebSocket, WebSocketDisconnect, HTTPException
from templates_engine import templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse
from sqlmodel import Session, select
from models import Product, PaymentReport, User, VendorBranding, Order, OrderItem
from db import get_session
from notify import ws_manager
from sms import send_sms
from config import PAYMENT_INFO, SELLER_MOBILE
from routers.store_helpers import resolve_store, build_theme
import secrets, asyncio, json

DEFAULT_IMAGE_URL = "/static/img/product_placeholder.png"

router = APIRouter(prefix="", tags=["Public"])

def _get_user_by_slug(session: Session, slug: str) -> User:
    user = session.exec(select(User).where(User.slug == slug)).first()
    if not user: raise HTTPException(status_code=404, detail="Vendedor no encontrado")
    return user

def _get_cart(request: Request):
  # Carrito en sesión: [{"product_id": int, "qty": int}, ...]
  cart = request.session.get("cart", [])
  # Sanitiza qty
  for it in cart:
      it["qty"] = max(1, int(it.get("qty", 1)))
  return cart

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
@router.post("/u/{slug}/modal-action")
def modal_action(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    intent: str = Form(...),                # 'cart' o 'report'
    product_id: int = Form(...),
    qty: int = Form(1),
    amount_type: int = Form(50),            # 50 o 100
    payer_name: str = Form(""),
    phone: str | None = Form(None),
):
    # 1) Busca producto y precio confiable en DB
    product = session.get(Product, product_id)
    if not product:
        return RedirectResponse(f"/u/{slug}?err=product_not_found", status_code=303)
    qty = max(1, int(qty))

    if intent == "cart":
        # 2A) Añade al carrito (implementación según tu app)
        # p.ej. guardar en sesión o en tabla CartItem
        cart = request.session.get("cart", [])
        cart.append({"product_id": product.id, "qty": qty})
        request.session["cart"] = cart
        return RedirectResponse(f"/u/{slug}?ok=added_to_cart", status_code=303)

    # intent == "report" → crear/registrar pago
    # 2B) Calcula monto en servidor (nunca confíes en el cliente)
    price = float(product.price or 0)
    base = price * qty
    amount = base if int(amount_type) == 100 else base / 2

    # 3) Crea Order (+ OrderItem) si tu flujo lo requiere, o solo PaymentReport
    order = Order()  # completa campos necesarios de tu esquema
    session.add(order)
    session.commit()
    session.refresh(order)

    item = OrderItem(order_id=order.id, product_id=product.id, qty=qty, unit_price=price)
    session.add(item)
    session.commit()

    pr = PaymentReport(
        order_id=order.id,
        amount=amount,
        payer_name=payer_name.strip(),
        method="reported",  # o el que toque
        reference="",
        notes=f"Via modal {slug}",
    )
    session.add(pr)
    session.commit()

    return RedirectResponse(f"/u/{slug}?ok=payment_reported", status_code=303)


@router.post("/u/{slug}/report-payment")
async def public_report_payment(
    slug: str,
    product_id: int = Form(...),
    qty: int = Form(...),
    amount_type: str = Form(...),       # "50" o "100"
    payer_name: str = Form(""),         # viene del formulario; puede venir vacío
    phone: str = Form(""),              # hoy no se guarda en modelos; lo dejamos por si lo usas en notificaciones
    session: Session = Depends(get_session),
):
    """
    Flujo minimalista para respetar NOT NULL en paymentreport.order_id:
    1) Resolver tienda + producto
    2) Calcular montos (50%/100%)
    3) Crear Order(total_amount, status="reported")
    4) Crear OrderItem(order_id, product_id, qty, unit_price)
    5) Crear PaymentReport(order_id, payer_name, method="REPORTED", reference="", amount, notes="")
    """

    # 1) Resolver tienda por slug
    user = session.exec(select(User).where(User.slug == slug)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Vendedor no encontrado")

    # 2) Producto y pertenencia
    product = session.get(Product, product_id)
    if not product or product.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Producto inválido")

    # 3) Normalizaciones
    try:
        qty = max(1, int(qty))
    except Exception:
        qty = 1

    price = float(product.price or 0.0)
    factor = 0.5 if amount_type == "50" else 1.0
    subtotal = price * qty
    amount = round(subtotal * factor, 2)

    # 4) Crear Order (tu modelo: total_amount + status)
    order = Order(
        total_amount=subtotal,   # monto base del pedido (antes del posible abono 50/100)
        status="reported",       # estado inicial mínimo
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    # 5) Crear OrderItem (tu modelo: unit_price)
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        qty=qty,
        unit_price=price,
    )
    session.add(item)
    session.commit()

    # 6) Crear PaymentReport con strings válidos (no NULL)
    report = PaymentReport(
        order_id=order.id,
        payer_name=(payer_name or "Cliente").strip(),
        method="REPORTED",        # string obligatorio; puedes cambiar a "ZELLE"/"CASH" si luego lo recoges del form
        reference="",             # string obligatorio; si luego agregas campo en el form, reemplaza aquí
        amount=amount,
        notes="",                 # opcional (tiene default "")
    )
    session.add(report)
    session.commit()
    session.refresh(report)

    # 7) Notificaciones por WS (opcional)
    payload = {
        "type": "payment_reported",
        "report": {
            "id": report.id,
            "order_id": order.id,
            "product_id": product.id,
            "product_name": product.name,
            "qty": qty,
            "amount": amount,
            "payer_name": report.payer_name,
        }
    }
    try:
        asyncio.create_task(ws_manager.broadcast(json.dumps(payload)))
    except Exception:
        pass

    # 8) Respuesta JSON mínima (tu front ya la consume)
    return JSONResponse({"ok": True, "report_id": report.id, "order_id": order.id, "amount": amount})

@router.get("/u/{slug}/cart.json")
def cart_json(slug: str, request: Request, session: Session = Depends(get_session)):
    cart = _get_cart(request)
    items = []
    total = 0.0
    for it in cart:
        p = session.get(Product, int(it["product_id"]))
        if not p:
            continue
        price = float(p.price or 0)
        qty = int(it["qty"])
        subtotal = price * qty
        total += subtotal
        items.append({
            "product_id": p.id,
            "name": p.name,
            "price": price,
            "qty": qty,
            "image_url": getattr(p, "image_url", None) or "",
            "subtotal": subtotal,
        })
    return {"items": items, "total": total}

@router.get("/u/{slug}/cart/count.json")
def cart_count(slug: str, request: Request):
    cart = request.session.get("cart", [])
    return {"count": len(cart)}

@router.post("/u/{slug}/cart-modal-action")
def cart_modal_action(
    slug: str,
    request: Request,
    session: Session = Depends(get_session),
    intent: str = Form(...),                 # 'report_cart' | 'empty_cart'
    amount_type: int = Form(50),             # 50 o 100 (solo para report_cart)
    payer_name: str = Form(""),
    phone: str | None = Form(None),
):
    cart = _get_cart(request)

    # Vaciar carrito (opcional)
    if intent == "empty_cart":
        request.session["cart"] = []
        return RedirectResponse(f"/u/{slug}?ok=cart_emptied", status_code=303)

    if intent != "report_cart":
        raise HTTPException(status_code=400, detail="Intent inválido")

    if not cart:
        return RedirectResponse(f"/u/{slug}?err=empty_cart", status_code=303)

    # 1) Recalcular precios y total en servidor
    total = 0.0
    resolved = []
    for it in cart:
        p = session.get(Product, int(it["product_id"]))
        if not p:
            continue
        price = float(p.price or 0)
        qty = int(it["qty"])
        total += price * qty
        resolved.append((p, qty, price))
    if not resolved:
        return RedirectResponse(f"/u/{slug}?err=invalid_cart", status_code=303)

    # 2) Crear Order + OrderItems
    order = Order()  # completa campos necesarios (status, timestamps, etc.)
    session.add(order)
    session.commit()
    session.refresh(order)

    for p, qty, price in resolved:
        session.add(OrderItem(order_id=order.id, product_id=p.id, qty=qty, unit_price=price))
    session.commit()

    # 3) Calcular monto a reportar (50% o 100%)
    amount = total if int(amount_type) == 100 else (total / 2.0)

    # 4) Crear PaymentReport asociado a la orden
    pr = PaymentReport(
        order_id=order.id,
        amount=amount,
        payer_name=payer_name.strip(),
        method="reported",
        reference="",
        notes=f"Cart modal {slug}",
    )
    session.add(pr)
    session.commit()

    # 5) (opcional) Vaciar carrito tras reportar
    request.session["cart"] = []

    return RedirectResponse(f"/u/{slug}?ok=order_reported", status_code=303)

