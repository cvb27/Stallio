from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from config import ADMIN_EMAIL, ADMIN_PASSWORD, BASE_URL, RESET_TOKEN_TTL_MIN
from sqlmodel import Session, select
from db import get_session
from models import User, PasswordReset
from security import hash_password, verify_password
from pydantic import EmailStr
from starlette.status import HTTP_302_FOUND, HTTP_303_SEE_OTHER
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from notify import send_email
import re, secrets, hashlib


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

    # 1) Validación de duplicado
    exists = session.exec(select(User).where(User.email == email)).first()
    if exists:
        return templates.TemplateResponse("admin/signup.html", {
                "request": request,
                "error": "Ese correo ya está registrado.",
                "email": email,
                "name": name,
                }, status_code=400)

    # 2) Genera slug único
    base = _slugify(name or email.split("@")[0])
    slug = base
    i = 2
    while session.exec(select(User).where(User.slug == slug)).first():
        slug = f"{base}-{i}"; i += 1

    # 3) Hash de contraseña
    pwd_hash, salt = hash_password(password)

    # 4) Crea usuario
    u = User(
        email=email, 
        name=name.strip() or None, 
        password_hash=pwd_hash, 
        salt=salt, 
        slug=slug
        )

    session.add(u); 
    session.commit(); 
    session.refresh(u)

    # 5) Autologin vendor
    request.session.clear()  # limpia cualquier estado previo
    request.session["user_email"] = u.email
    request.session["user_id"] = u.id          # ← CLAVE para filtrar
    request.session["user_name"]  = (u.name or u.email) # Guarda el nombre de usuario para el layout.
    request.session["user_slug"]  = u.slug 

    return RedirectResponse(
        f"admin/{u.slug}/dashboard", 
        status_code=HTTP_303_SEE_OTHER
        )


# ========== LOGIN ==========
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

    # 1) Admin por credenciales fijas
    if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
         # Si login correcto, redirige al master users.
        request.session.clear()   # ← limpia cualquier rastro de vendor
        request.session["admin_email"] = email          # ← sesión creada
        request.session["user_name"] = "Administrador"  # Muestra el nombre de user en el layout.
        return RedirectResponse("/admin/users", status_code=HTTP_303_SEE_OTHER)
    
    # 2) Busca usuario vendor/admin en BD
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Credenciales inválidas"},
            status_code=401,
        )
    
    # 3) Luego busca si la cuenta esta activa.
    if getattr(user, "is_active", True) is False:
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Tu cuenta está desactivada"},
            status_code=403,
        )
    
    # 4) Verifica contraseña
    if not verify_password(password, user.salt, user.password_hash):
        return templates.TemplateResponse(
            "admin/auth.html",
            {"request": request, "error": "Credenciales inválidas"},
            status_code=401,
        )
    
    # 5) Si esta todo bien, redirige por rol
    role = getattr(user, "role", "vendor")

    request.session.clear()
    if role == "admin":
        request.session["admin_email"] = user.email
        request.session["user_name"] = (user.name or "Administrador")
        return RedirectResponse("/admin/users", status_code=HTTP_303_SEE_OTHER)

   # Vendedor
    request.session.clear()  # ← limpia cualquier rastro de admin
    request.session["user_email"] = user.email
    request.session["user_id"] = user.id        # ← CLAVE para la separacion de los perfiles de vendedor.
    request.session["user_name"]  = (user.name or user.email)  # Guarda el nombre
    request.session["user_slug"]  = user.slug 

    return RedirectResponse(
        f"admin/{user.slug}/dashboard", 
        status_code=HTTP_303_SEE_OTHER
        )


# ========== LOGOUT ==========
@router.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

# ========== 1) FORM OLVIDÉ MI CONTRASEÑA ==========

@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request):
    return templates.TemplateResponse("admin/forgot.html", {"request": request})


# ========= 2) POST: ENVIAR EMAIL CON TOKEN =========

@router.post("/forgot", response_class=HTMLResponse)
def forgot_submit(
    request: Request,
    email: str = Form(...)
    , session: Session = Depends(get_session)
):
    # A) Buscar usuario (pero no revelar si existe o no)
    user = session.exec(select(User).where(User.email == email)).first()

    # B) Siempre responder igual para evitar enumeración
    #    Si existe, creamos y enviamos token.
    if user:
        # Token aleatorio
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MIN)

        pr = PasswordReset(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        session.add(pr)
        session.commit()

        reset_url = f"{BASE_URL}/reset?token={token}"

        subject = "Restablece tu contraseña"
        body = (
            f"Hola,\n\n"
            f"Para restablecer tu contraseña haz clic en el siguiente enlace:\n{reset_url}\n\n"
            f"Este enlace expira en {RESET_TOKEN_TTL_MIN} minutos.\n\n"
            f"Si no solicitaste este cambio, ignora este correo."
        )
        try:
            send_email(to=email, subject=subject, body=body)
        except Exception:
            # No exponemos detalles; el flujo sigue siendo el mismo
            pass

    # C) Redirigir con mensaje genérico
    return RedirectResponse("/forgot?sent=1", status_code=302)

# ========= 3) FORM INGRESAR NUEVA CONTRASEÑA =========
@router.get("/reset", response_class=HTMLResponse)
def reset_form(request: Request, token: str, session: Session = Depends(get_session)):
    # Validar token
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    pr = session.exec(
        select(PasswordReset).where(PasswordReset.token_hash == token_hash)
    ).first()

    if (not pr) or pr.used_at or (pr.expires_at < datetime.utcnow()):
        # Token inválido/expirado/usado
        return templates.TemplateResponse("/reset_invalid.html", {"request": request})

    return templates.TemplateResponse("/reset.html", {"request": request, "token": token})

# ========= 4) POST: GUARDAR NUEVA CONTRASEÑA =========
@router.post("/reset", response_class=HTMLResponse)
def reset_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    session: Session = Depends(get_session)
):
    if len(password) < 8:
        return templates.TemplateResponse("/reset.html", {
            "request": request, "token": token, "err": "La contraseña debe tener al menos 8 caracteres."
        })
    if password != password2:
        return templates.TemplateResponse("/reset.html", {
            "request": request, "token": token, "err": "Las contraseñas no coinciden."
        })

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    pr = session.exec(
        select(PasswordReset).where(PasswordReset.token_hash == token_hash)
    ).first()

    if (not pr) or pr.used_at or (pr.expires_at < datetime.utcnow()):
        return templates.TemplateResponse("/reset_invalid.html", {"request": request})

    # Cargar usuario y actualizar contraseña
    user = session.exec(select(User).where(User.id == pr.user_id)).first()
    if not user:
        return templates.TemplateResponse("/reset_invalid.html", {"request": request})

    # Hash de contraseña (ajusta si ya tienes tu helper de hashing)
    user.password_hash = generate_password_hash(password)

    # Marcar token como usado
    pr.used_at = datetime.utcnow()

    session.add(user)
    session.add(pr)
    session.commit()

    # Redirigir a login con mensaje
    return RedirectResponse("/login?reset_ok=1", status_code=302)