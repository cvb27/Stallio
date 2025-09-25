
from fastapi import APIRouter, Request, Depends, HTTPException, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from models import PaymentReport, Product, DispatchedOrder
from notify import ws_manager
from db import get_session
import asyncio, json

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/master/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if "admin_email" not in request.session:
        return RedirectResponse("master/login", status_code=302)
    return templates.TemplateResponse(
        "master/dashboard.html",
        {"request": request, "email": request.session["admin_email"]}
    )