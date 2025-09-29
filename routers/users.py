from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, delete
from db import get_session
from models import User, Product, PaymentReport, DispatchedOrder
from starlette.status import HTTP_302_FOUND
from sqlalchemy import or_, func

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])
templates = Jinja2Templates(directory="templates")


# ========== ADMIN: gestión de usuarios ==========
def _require_admin(request: Request):
    # Reutiliza tu mecanismo existente (usabas "admin_email" en sesión)
    if "admin_email" not in request.session:
        raise HTTPException(status_code=401, detail="No autenticado como admin")
    
@router.get("/", response_class=HTMLResponse)
def admin_users_page(
    request: Request, 
    session: Session = Depends(get_session), 
    q: str | None = None
    ):

    if "admin_email" not in request.session:
        return RedirectResponse("/login", status_code=302)

    stmt = select(User).order_by(User.created_at.desc())
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = (
            select(User)
            .where(or_(func.lower(User.email).like(like),
                       func.lower(User.name).like(like)))
            .order_by(User.created_at.desc())
        )

    users = session.exec(stmt).all()

    return templates.TemplateResponse(
        "master/users.html",
        {
            "request": request,
            "users": users,
            "q": q or "",
        },
    )
""""
    _require_admin(request)
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        # Búsqueda simple por email o nombre
        like = f"%{q.strip().lower()}%"
        from sqlalchemy import or_, func
        stmt = select(User).where(
            or_(func.lower(User.email).like(like), func.lower(User.name).like(like))
        ).order_by(User.created_at.desc())

    users = session.exec(stmt).all()
    return templates.TemplateResponse("master/users.html", {
        "request": request,
        "users": users,
        "q": q or ""
    })
"""

@router.post("/{user_id}/deactivate")
def admin_deactivate_user(user_id: int, request: Request, session: Session = Depends(get_session)):
    _require_admin(request)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.is_active = False
    session.add(u); session.commit()
    return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)


@router.post("/{user_id}/activate")
def admin_activate_user(user_id: int, request: Request, session: Session = Depends(get_session)):
    _require_admin(request)
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.is_active = True
    session.add(u); session.commit()
    return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

# (Opcional) Cambiar rol rápidamente (promover a admin o devolver a vendor)
@router.post("/{user_id}/role")
def admin_change_role(user_id: int, role: str = Form(...), request: Request = None, session: Session = Depends(get_session)):
    _require_admin(request)
    if role not in ("admin", "vendor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.role = role
    session.add(u); session.commit()
    return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

# Pagina de confirmacion.
@router.get("/{user_id}/delete", response_class=HTMLResponse)
def master_vendor_delete_confirm(user_id: int, request: Request, session: Session = Depends(get_session)):
    _require_admin(request)
    vendor = session.get(User, user_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor no encontrado")
    # Para evitar borrar admins por error
    if getattr(vendor, "role", "vendor") == "admin":
        raise HTTPException(status_code=400, detail="No se puede eliminar un admin")
    # Contar objetos asociados
    prod_count = session.exec(select(Product).where(Product.owner_id == vendor.id)).all()
    pr_count   = session.exec(select(PaymentReport).where(PaymentReport.owner_id == vendor.id)).all()
    disp_count = session.exec(select(DispatchedOrder).where(DispatchedOrder.owner_id == vendor.id)).all()
    return templates.TemplateResponse("master/vendor_delete.html", {
        "request": request,
        "vendor": vendor,
        "prod_count": prod_count,
        "pr_count": pr_count,
        "disp_count": disp_count,
    })

# Acción de eliminación definitiva ---
@router.post("/{user_id}/delete")
def master_vendor_delete_do(user_id: int, request: Request, session: Session = Depends(get_session)):
    _require_admin(request)
    vendor = session.get(User, user_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor no encontrado")
    if getattr(vendor, "role", "vendor") != "vendor":
        raise HTTPException(status_code=400, detail="Solo se pueden eliminar vendors")

    # 1) Eliminar dependencias en orden seguro (sin FK en cascada)
    session.exec(delete(DispatchedOrder).where(DispatchedOrder.owner_id == vendor.id))
    session.exec(delete(PaymentReport).where(PaymentReport.owner_id == vendor.id))
    session.exec(delete(Product).where(Product.owner_id == vendor.id))

    # 2) Eliminar usuario
    session.delete(vendor)
    session.commit()

    # 3) Redirigir a la lista de usuarios (master)
    return RedirectResponse("/admin/users", status_code=303)

# (Opcional) Contador rápido en JSON (útil para tarjetas métricas)
@router.get("/count.json")
def admin_users_count(request: Request, session: Session = Depends(get_session)):
    _require_admin(request)
    total = session.exec(select(User)).all()
    act = len([u for u in total if u.is_active])
    return JSONResponse({"total": len(total), "activos": act, "inactivos": len(total) - act})
