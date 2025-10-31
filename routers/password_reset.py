from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from email_validator import validate_email, EmailNotValidError

from models import User
from db import get_session # your existing dependency
from utils.security import hash_password
from services.emailer import send_email

# Import settings from main (or a config module)
from config import SECRET_KEY, PASSWORD_RESET_TOKEN_MAX_AGE, APP_BASE_URL

router = APIRouter(prefix="/auth", tags=["Password Reset"])
templates = Jinja2Templates(directory="templates")


# --- 1) Ask for email ---
@router.get("/forgot", response_class=HTMLResponse)
async def forgot_get(request: Request):
    return templates.TemplateResponse("auth/forgot.html", {"request": request, "sent": False})


@router.post("/forgot", response_class=HTMLResponse)
async def forgot_post(
    request: Request,
    email: str = Form(...),
    session: Session = Depends(get_session),
    ):


    # Normalize + validate
    try:
        email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError:
        # IMPORTANT: never reveal which emails exist; same generic response.
        return templates.TemplateResponse("auth/forgot.html", {"request": request, "sent": True})


    user = session.exec(select(User).where(User.email == email)).first()


    if user:
        token = generate_reset_token(SECRET_KEY, user.id, user.reset_token_version)
        reset_url = f"{APP_BASE_URL}/auth/reset?token={token}"


        # Render a very simple text email. In real app, use Jinja2 template if desired.
        subject = "Reset your Stallio password"
        with open("templates/auth/email_reset.txt", "r", encoding="utf-8") as f:
            body = f.read().format(reset_url=reset_url)
        send_email(user.email, subject, body)


    # Always show the same result to avoid user enumeration
    return templates.TemplateResponse("auth/forgot.html", {"request": request, "sent": True})


# --- 2) Let user set a new password (GET shows form if token ok) ---
@router.get("/reset", response_class=HTMLResponse)
async def reset_get(request: Request, token: str):
    user_id, version, error = verify_reset_token(SECRET_KEY, token, PASSWORD_RESET_TOKEN_MAX_AGE)
    if error is not None:
        return templates.TemplateResponse("auth/reset.html", {
            "request": request,
            "token": token,
            "error": error,
            "ok": False,
        })
    return templates.TemplateResponse("auth/reset.html", {
        "request": request,
        "token": token,
        "error": None,
        "ok": True,
    })


# --- 3) Persist the new password (POST) ---
@router.post("/reset")
async def reset_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    session: Session = Depends(get_session),
):
    # Basic checks
    if password != password2:
        return templates.TemplateResponse("auth/reset.html", {
            "request": request,
            "token": token,
            "error": "Passwords do not match",
            "ok": False,
        })
    if len(password) < 8:
        return templates.TemplateResponse("auth/reset.html", {
            "request": request,
            "token": token,
            "error": "Use at least 8 characters",
            "ok": False,
        })

    user_id, version, error = verify_reset_token(SECRET_KEY, token, PASSWORD_RESET_TOKEN_MAX_AGE)
    if error is not None:
        return templates.TemplateResponse("auth/reset.html", {"request": request, "token": token, "error": error, "ok": False})


    user = session.get(User, user_id)
    if not user:
        return templates.TemplateResponse("auth/reset.html", {"request": request, "token": token, "error": "invalid", "ok": False})

    # Check the token version still matches the user's current version
    if user.reset_token_version != version:
        return templates.TemplateResponse("auth/reset.html", {"request": request, "token": token, "error": "invalid", "ok": False})

    # Save new password + invalidate older tokens by bumping version
    user.password_hash = hash_password(password)
    user.reset_token_version += 1
    session.add(user)
    session.commit()


    # Redirect to login with a small flash via query param
    response = RedirectResponse(url="/login?reset=1", status_code=303)
    return response