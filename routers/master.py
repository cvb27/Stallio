
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from db import get_session
from models import User, VendorBranding
from routers.store_helpers import get_branding_by_owner
from templates_engine import templates


router = APIRouter()

"""
    Master dashboard: list of vendors/users.

         For each user we now also fetch their VendorBranding (if any)
         and compute the public home URL: /u/{branding.slug}
    """

@router.get("/master/users", response_class=HTMLResponse)
async def dashboard_page(request: Request, session: Session = Depends(get_session)):

    if "admin_email" not in request.session:
        return RedirectResponse("/master/login", status_code=302)

     # 1) Get all users (here you can filter only vendors if you want)
    users = session.exec(select(User).order_by(User.id.desc())).all()

    # 2) Build a list of rows with extra info (branding + public_url)
    rows = []
    for u in users:
        # CHG: get branding for this owner (may be None)
        branding = get_branding_by_owner(session, u.id)

        # CHG: compute public URL only if branding exists and has slug
        public_url = None
        if branding and getattr(branding, "slug", None):
            public_url = f"/u/{branding.slug}"

        rows.append({
            "user": u,
            "branding": branding,
            "public_url": public_url,
        })

    # 3) Pass rows to the template instead of raw users    
    return templates.TemplateResponse(
        "master/users.html",
        {"request": request, 
         "users": users,  # CHG: agregamos users para que el template pueda iterar
         "rows": rows, 
         "email": request.session["admin_email"]}
    )