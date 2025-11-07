# Gestión súper simple del carrito guardado en sesión.

from typing import List, Dict
from fastapi import Request

CartItem = Dict[str, int]  # {"product_id": int, "qty": int}

def _ensure_cart(request: Request) -> List[CartItem]:
    cart = request.session.get("cart")
    if not isinstance(cart, list):
        cart = []
        request.session["cart"] = cart
    return cart

def add_item(request: Request, product_id: int, qty: int = 1) -> None:
    cart = _ensure_cart(request)
    for it in cart:
        if it["product_id"] == product_id:
            it["qty"] = max(1, it["qty"] + qty)
            request.session.modified = True
            return
    cart.append({"product_id": product_id, "qty": max(1, qty)})
    request.session["cart"] = cart
    request.session.modified = True

def set_qty(request: Request, product_id: int, qty: int) -> None:
    cart = _ensure_cart(request)
    for it in cart:
        if it["product_id"] == product_id:
            if qty <= 0:
                cart.remove(it)
            else:
                it["qty"] = qty
            request.session["cart"] = cart
            request.session.modified = True
            return

def remove_item(request: Request, product_id: int) -> None:
    set_qty(request, product_id, 0)

def clear(request: Request) -> None:
    request.session["cart"] = []
    request.session.modified = True