# Ver/editar carrito y hacer el reporte único.

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlmodel import Session, select
from typing import List, Dict
from fastapi.templating import Jinja2Templates

from db import get_session
from models import Product, Order, OrderItem, PaymentReport  # asumiendo que ya existe  /  ver sección C
from utils.cart import add_item, set_qty, remove_item, clear as cart_clear

router = APIRouter(tags=["Cart"])
templates = Jinja2Templates(directory="templates")

# --------- Vistas de carrito ---------

@router.get("/cart", response_class=HTMLResponse)
def cart_view(request: Request, session: Session = Depends(get_session)):
    raw = request.session.get("cart", [])
    items = []
    total = 0
    for it in raw:
        prod = session.get(Product, it["product_id"])
        if not prod:
            continue
        line_total = (prod.price or 0) * it["qty"]
        total += line_total
        items.append({"product": prod, "qty": it["qty"], "line_total": line_total})
    return templates.TemplateResponse(
        "cart/cart.html",
        {"request": request, "items": items, "total": total},
    )

@router.post("/cart/add")
def cart_add(
    request: Request,
    product_id: int = Form(...),
    qty: int = Form(1),
):
    cart = request.session.get("cart", {})
    cart[str(product_id)] = cart.get(str(product_id), 0) + max(1, int(qty))
    request.session["cart"] = cart
    # add_item(request, product_id, qty)
    # Redirige a donde venía (referer) o a /cart
    referer = request.headers.get("referer") or "/cart"
    return RedirectResponse(url=referer, status_code=303)

@router.post("/cart/set-qty")
def cart_set_qty(
    request: Request,
    product_id: int = Form(...),
    qty: int = Form(...),
):
    set_qty(request, product_id, qty)
    return RedirectResponse(url="/cart", status_code=303)

@router.post("/cart/remove")
def cart_remove(request: Request, product_id: int = Form(...)):
    remove_item(request, product_id)
    return RedirectResponse(url="/cart", status_code=303)

@router.post("/cart/clear")
def cart_clear_route(request: Request):
    cart_clear(request)
    return RedirectResponse(url="/cart", status_code=303)

# --------- Checkout / Reporte único ---------

@router.get("/checkout", response_class=HTMLResponse)
def checkout_get(request: Request, session: Session = Depends(get_session)):
    raw = request.session.get("cart", [])
    if not raw:
        return RedirectResponse(url="/", status_code=303)

    # Reutilizamos la misma lógica que /cart para mostrar resumen
    items = []
    total = 0
    for it in raw:
        prod = session.get(Product, it["product_id"])
        if not prod:
            continue
        line_total = (prod.price or 0) * it["qty"]
        total += line_total
        items.append({"product": prod, "qty": it["qty"], "line_total": line_total})

    return request.app.state.templates.TemplateResponse(
        "cart/checkout.html",
        {"request": request, "items": items, "total": total},
    )

@router.post("/checkout")
def checkout_post(
    request: Request,
    session: Session = Depends(get_session),
    payer_name: str = Form(...),
    payment_method: str = Form(...),   # ej: Zelle, Cash, Wire...
    reference: str = Form(...),        # número/nota que ingrese el comprador
    notes: str = Form(""),
):
    raw = request.session.get("cart", [])
    if not raw:
        return RedirectResponse(url="/", status_code=303)

    # 1) Resolver productos y total
    items = []
    total = 0
    for it in raw:
        prod = session.get(Product, it["product_id"])
        if not prod:
            continue
        qty = it["qty"]
        line_total = (prod.price or 0) * qty
        total += line_total
        items.append((prod, qty, line_total))

    # 2) Persistir un único Order + sus OrderItems + un PaymentReport
    #    Si ya tienes esos modelos/servicios, reutilízalos aquí.
    #    A continuación incluyo un ejemplo mínimo (ver sección C).

    
    order = Order(total_amount=total, status="reported")
    session.add(order)
    session.flush()  # para tener order.id

    for prod, qty, line_total in items:
        oi = OrderItem(order_id=order.id, product_id=prod.id, qty=qty, unit_price=prod.price or 0)
        session.add(oi)

    pr = PaymentReport(
        order_id=order.id,
        payer_name=payer_name,
        method=payment_method,
        reference=reference,
        amount=total,
        notes=notes,
    )
    session.add(pr)
    session.commit()

    # 3) Limpiar carrito y redirigir a confirmación
    request.session["cart"] = []
    request.session.modified = True

    return RedirectResponse(url=f"/orders/thanks?order_id={order.id}", status_code=303)