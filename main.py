from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from routers import dashboard, auth, public, products, support, users, master, vendor, share, orders
from config import SESSION_SECRET
from contextlib import asynccontextmanager
from notify import ws_manager
from db import init_db
from sqlmodel import SQLModel
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads"
VENDOR_LOGOS_DIR = UPLOADS_DIR / "vendor_logos"

# ⚠️ Crear carpetas ANTES de montar
STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
VENDOR_LOGOS_DIR.mkdir(parents=True, exist_ok=True)

# Comandos varios
# source .venv/bin/activate
# rm -rf __pycache__
# -uvicorn main:app --reload

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # crea tablas una sola vez al boot
    yield       # no hacemos nada al shutdown (ya migraste a WebSocket)


app = FastAPI(lifespan=lifespan)

# Sirve archivos estaticos (css, imagenes, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Sesiones (firma de cookies)
app.add_middleware(SessionMiddleware, secret_key="9ooiBgd3HLbFa3yyXpHCYiZD8xHD3Qa7")

# End point vacio para el error que venia de Chrome devtools
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_probe():
    return Response(status_code=204)


app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(vendor.router)
app.include_router(public.router)
app.include_router(products.router)
app.include_router(support.router)
app.include_router(users.router)
app.include_router(master.router)

app.include_router(share.router)
app.include_router(orders.router)




# ruta de prueba para verificar que la app que corre es esta
@app.get("/ping")
def ping():
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)