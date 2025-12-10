from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from templates_engine import templates
from sqlmodel import Session, select
from models import Product, User
from notify import ws_manager
from db import get_session
from storage_local import save_product_bytes, UPLOADS_DIR
import os, json
from datetime import timezone  # si no usas _iso(), puedes eliminar esta import

router = APIRouter(prefix="/admin/products", tags=["Admin Products"])

# Imagen por defecto para tarjetas sin foto
DEFAULT_IMAGE_URL = "/static/img/product_placeholder.png"


def _require_vendor(request: Request) -> int:
    """Devuelve el ID del vendor autenticado o 401."""
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(request.session["user_id"])


# --- Flash messages (utilidad simple guardada en sesión) ---
def flash(request: Request, message: str, category: str = "success"):
    flashes = request.session.get("_flashes", [])
    flashes.append({"message": message, "category": category})
    request.session["_flashes"] = flashes


def get_flashed_messages(request: Request):
    return request.session.pop("_flashes", [])


def _owner_id(request: Request) -> int:
    """Convenience: asegura auth y devuelve el user_id."""
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(uid)


# ================== LISTA / DASHBOARD ==================
@router.get("/", name="admin_products")
async def products_dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    """Renderiza el listado de productos del vendor autenticado."""
    owner_id = _owner_id(request)

    # 👇 nuevo: obtenemos el usuario dueño (tiene slug)
    vendor = session.get(User, owner_id)

    products = session.exec(
        select(Product)
        .where(Product.owner_id == owner_id)
        .order_by(Product.id.desc())
    ).all()
    messages = get_flashed_messages(request)
    return templates.TemplateResponse(
        "admin/products.html",  # sin slash inicial para consistencia
        {"request": request, 
         "products": products, 
         "messages": messages,
         "vendor": vendor,},
    )


# ================== CREAR ==================
@router.post("/create")
async def create_product(
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(0),
    description: str = Form(""),
    image: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    """Crea un producto. Si se adjunta imagen, se guarda en el volumen."""
    owner_id = _owner_id(request)

    # slug del dueño para organizar carpetas
    owner = session.get(User, owner_id)
    owner_slug = owner.slug if owner and owner.slug else str(owner_id)

    image_url = None
    if image and getattr(image, "filename", ""):
        content = await image.read()
        image_url = save_product_bytes(owner_slug, content, image.filename)

    p = Product(
        name=name.strip(),
        description=(description or "").strip() or None,
        price=price,
        stock=stock,
        image_url=image_url,
        owner_id=owner_id,
    )
    session.add(p)
    session.commit()
    session.refresh(p)

    # Notificar a la vista pública (si está abierta)
    try:
        await ws_manager.broadcast(json.dumps({"type": "products_changed"}))
    except Exception:
        pass

    flash(request, f"Producto '{p.name}' creado (ID {p.id}).", "success")
    return RedirectResponse("/admin/products", status_code=303)


# ================== EDITAR (form) ==================
@router.get("/{product_id}/edit", response_class=HTMLResponse)
def edit_product_page(
    product_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Muestra el formulario de edición para un producto del vendor."""
    owner_id = _require_vendor(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return templates.TemplateResponse("admin/product_edit.html", {"request": request, "p": p})


# ================== API JSON (admin) ==================
@router.get("/list.json")
def products_json(request: Request, session: Session = Depends(get_session)):
    """Devuelve los productos del vendor autenticado para la UI del admin."""
    owner_id = _owner_id(request)
    rows = session.exec(select(Product).where(Product.owner_id == owner_id)).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "stock": p.stock,
            "image_url": p.image_url or DEFAULT_IMAGE_URL,
            "created_at": p.created_at.isoformat(),
        }
        for p in rows]

# ================== UPDATE ==================
@router.post("/update/{product_id}")
async def update_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(0),
    category: str = Form(""),  # si no lo usas en el modelo, puedes quitar este campo del form
    description: str = Form(""),
    image: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    """Actualiza campos del producto y, opcionalmente, reemplaza la imagen."""
    owner_id = _require_vendor(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if image and getattr(image, "filename", ""):
        owner = session.get(User, owner_id)
        owner_slug = owner.slug if owner and owner.slug else str(owner_id)
        content = await image.read()
        p.image_url = save_product_bytes(owner_slug, content, image.filename)

    p.name = name.strip()
    p.price = price
    p.stock = stock
    p.description = (description or "").strip() or None

    session.add(p)
    session.commit()
    session.refresh(p)

    try:
        await ws_manager.broadcast(json.dumps({"type": "products_changed"}))
    except Exception:
        pass

    flash(request, f"Producto '{p.name}' actualizado.", "success")
    return RedirectResponse("/admin/products", status_code=303)


# ================== DELETE ==================
@router.post("/delete/{product_id}")
async def delete_product(
    product_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Elimina el producto. (El borrado físico de la imagen es opcional y seguro.)"""
    owner_id = _require_vendor(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Borrado seguro en el volumen si la URL apunta a /uploads/...
    try:
        if p.image_url and p.image_url.startswith("/uploads/"):
            rel = p.image_url[len("/uploads/"):]  # e.g. "products/<slug>/<file>.png"
            file_path = (UPLOADS_DIR / rel).resolve()
            # Evita borrar algo fuera del volumen por error de path
            if str(file_path).startswith(str(UPLOADS_DIR)) and file_path.exists():
                file_path.unlink()
    except Exception:
        pass  # no bloquea el borrado lógico

    session.delete(p)
    session.commit()

    try:
        await ws_manager.broadcast(json.dumps({"type": "products_changed"}))
    except Exception:
        pass

    flash(request, f"Producto '{p.name}' eliminado.", "warning")
    return RedirectResponse(url=request.url_for("admin_products"), status_code=303)
