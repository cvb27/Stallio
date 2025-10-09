from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from models import Product, User
from notify import ws_manager
from db import get_session
from datetime import timezone
from storage_local import save_product_image
import os, json, asyncio, uuid, shutil

router = APIRouter(prefix="/admin/products", tags=["Admin Products"])
templates = Jinja2Templates(directory="templates")

DEFAULT_IMAGE_URL = "/static/img/product_placeholder.png"

def _require_vendor(request: Request) -> int:
    if "user_id" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(request.session["user_id"])

# --- Utilidades de notificaciones (flash messages) ---
def flash(request: Request, message: str, category: str = "success"):
    flashes = request.session.get("_flashes", [])
    flashes.append({"message": message, "category": category})
    request.session["_flashes"] = flashes

def get_flashed_messages(request: Request):
    return request.session.pop("_flashes", [])

def _owner_id(request: Request) -> int:
    uid = request.session.get("user_id")
    if not uid: raise HTTPException(status_code=401, detail="No autenticado")
    return int(uid)

def _iso(dt):
    if not dt: return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

# ================== LISTA / DASHBOARD ==================
@router.get("/",  name="admin_products")
async def products_dashboard(
    request: Request, 
    session: Session = Depends(get_session)):
    owner_id = _owner_id(request)
    # FIX: filtrar por dueño
    products = session.exec(
        select(Product).where(Product.owner_id == owner_id).order_by(Product.id.desc())
    ).all()
    messages = get_flashed_messages(request)
    return templates.TemplateResponse(
        "/admin/products.html",
        {"request": request, "products": products, "messages": messages},
)


# ================== CREAR ==================
@router.post("/create")
async def create_product(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(0),
    description: str = Form(""),
    image: UploadFile | None = File(None),
):
    owner_id = _owner_id(request)
    owner = session.get(User, owner_id)
    slug = owner.slug or str(owner_id)

    image_url = None
    if image and getattr(image, "filename", ""):
        content = await image.read()
        if content:
            image_url = save_product_image(slug, content, image.filename)

    p = Product(
        name=name.strip(),
        description=(description or "").strip() or None,
        price=price,
        stock=stock,
        image_url=image_url,   # ← guarda URL pública /uploads/...
        owner_id=owner_id,
    )
    session.add(p); session.commit(); session.refresh(p)
    return RedirectResponse(url=request.url_for("admin_products"), status_code=303)
    # return {"ok": True, "product_id": p.id, "image_url": p.image_url}
# ================== EDITAR (form) ==================
@router.get("/{product_id}/edit", response_class=HTMLResponse)
def edit_product_page(product_id: int, request: Request, session: Session = Depends(get_session)):
    owner_id = _require_vendor(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return templates.TemplateResponse("admin/product_edit.html", {"request": request, "p": p})

# ================== EDITAR (form) ==================

@router.get("/list.json")
def products_json(request: Request, session: Session = Depends(get_session)):
    """
    Devuelve el listado del vendor autenticado con URLs normalizadas:
    - /uploads/... (persistente)
    - /static/uploads/... -> /uploads/legacy/... (compatibilidad)
    """
    owner_id = _owner_id(request)
    rows = session.exec(select(Product).where(Product.owner_id == owner_id)).all()
    return [{
        "id": p.id, 
        "name": p.name, 
        "price": p.price, 
        "stock": p.stock,
        "image_url": p.image_url or DEFAULT_IMAGE_URL, 
        "created_at": p.created_at.isoformat()
    } for p in rows]

@router.get("/u/{slug}/products.json")
def public_products_json(slug: str, session: Session = Depends(get_session)):
    user, _ = resolve_store(session, slug)
    rows = session.exec(select(Product).where(Product.owner_id == user.id)).all()
    return [{
        "id": p.id, "name": p.name, "price": p.price, "stock": p.stock,
        "image_url": p.image_url or "/static/img/product_placeholder.png",
        "created_at": p.created_at.isoformat(),
    } for p in rows]

# ================== UPDATE ==================
@router.post("/update/{product_id}")
async def update_product(
    product_id: int,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    price: float = Form(...),
    stock: int = Form(0),
    description: str = Form(""),
    image: UploadFile | None = File(None),
):
    owner_id = _owner_id(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id: raise HTTPException(status_code=404, detail="Producto no encontrado")

    p.name = name.strip(); p.price = price; p.stock = stock
    p.description = (description or "").strip() or None

    if image and getattr(image, "filename", ""):
        owner = session.get(User, owner_id)
        slug = owner.slug or str(owner_id)
        content = await image.read()
        if content:
            p.image_url = save_product_image(slug, content, image.filename)

    session.add(p); session.commit(); session.refresh(p)
    return RedirectResponse(url=request.url_for("admin_products"), status_code=303)
    # return {"ok": True, "product_id": p.id, "image_url": p.image_url}
# ================== DELETE ==================

@router.post("/delete/{product_id}")
async def delete_product(
    product_id: int, 
    request: Request, 
    session: Session = Depends(get_session)):
    owner_id = _require_vendor(request)
    p = session.get(Product, product_id)
    if not p or p.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if p.image_url:
        file_path = p.image_url.lstrip("/")
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass

    session.delete(p)
    session.commit()

    try:
        await ws_manager.broadcast(json.dumps({"type": "products_changed"}))
    except Exception:
        pass

    flash(request, f"Producto '{p.name}' eliminado.", "warning")
    return RedirectResponse(url=request.url_for("admin_products"), status_code=303)
    