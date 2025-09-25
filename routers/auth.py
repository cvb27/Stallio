from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from config import ADMIN_EMAIL, ADMIN_PASSWORD
from sqlmodel import Session, select
from db import get_session
from models import User
from security import hash_password, verify_password
from pydantic import EmailStr
from starlette.status import HTTP_302_FOUND, HTTP_303_SEE_OTHER
import re, secrets


router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or secrets.token_hex(3)

# ========== SIGNUP ==========
@router.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    # Si ya hay alguien logueado, puedes redirigir donde prefieras
    return templates.TemplateResponse("admin/signup.html", {"request": request})

@router.post("/signup")
def signup_post(
    request: Request,
    email: EmailStr = Form(...),
    name: str = Form(""),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    # ✅ normaliza email
    email = str(email).strip().lower()

    exists = session.exec(select(User).where(User.email == email)).first()
    if exists:
        return templates.TemplateResponse("admin/signup.html", {
                "request": request,
                "error": "Ese correo ya está registrado.",
                "email": email,
                "name": name,
                }, status_code=400)

    base = _slugify(name or email.split("@")[0])
    slug = base
    i = 2
    while session.exec(select(User).where(User.slug == slug)).first():
        slug = f"{base}-{i}"; i += 1

    pwd_hash, salt = hash_password(password)
    u = User(email=email, name=name.strip() or None, password_hash=pwd_hash, salt=salt, slug=slug)
    session.add(u); 
    session.commit(); 
    session.refresh(u)

    # autologin vendedor a su propio panel
    request.session["user_email"] = u.email
    request.session["user_id"] = u.id          # ← CLAVE para filtrar
    request.session["user_name"]  = (u.name or u.email) # Guarda el nombre de usuario para el layout.
    request.session["user_slug"]  = u.slug 
    return RedirectResponse(f"admin/{u.slug}/dashboard", status_code=HTTP_303_SEE_OTHER)


# Formulario de login
@router.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(
        "admin/auth.html",
        {"request": request, "error": None}
    )

# Procesa credenciales
@router.post("/login")
async def login(
    request: Request, 
    email: str = Form(...), 
    password: str = Form(...),
    session: Session = Depends(get_session),
):
     # Normaliza email
    email = str(email).strip().lower()

    # Login para admin
    if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
         # Si login correcto, redirige al master users.
        request.session.clear()   # ← limpia cualquier rastro de vendor
        request.session["admin_email"] = email          # ← sesión creada
        request.session["user_name"] = "Administrador"  # Muestra el nombre de user en el layout.
        return RedirectResponse("/admin/users", status_code=302)
    
    # Si no, va al db a buscar usuarios vendors
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Credenciales inválidas"}
        )
    # Luego busca si la cuenta esta activa.
    if hasattr(user, "is_active") and not user.is_active:
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Tu cuenta está desactivada"}
        )
    
    # Luego verifica hash con sal
    if not verify_password(password, user.salt, user.password_hash):
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Credenciales inválidas"}
        )
    
    # Si esta todo bien, redirige por rol
    if getattr(user, "role", "vendor") == "admin":
        request.session["admin_email"] = user.email
        return RedirectResponse("/users", status_code=302)


   # Vendedor
    request.session.clear()  # ← limpia cualquier rastro de admin
    request.session["user_email"] = user.email
    request.session["user_id"] = user.id        # ← CLAVE para la separacion de los perfiles de vendedor.
    request.session["user_name"]  = (user.name or user.email)  # Guarda el nombre
    request.session["user_slug"]  = user.slug 
    return RedirectResponse(f"admin/{user.slug}/dashboard", status_code=HTTP_303_SEE_OTHER)
    # return RedirectResponse("/dashboard", status_code=302)

@router.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
