import os
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from routers import dashboard, auth, public, products, support, users, master, vendor, share, orders, debug
from contextlib import asynccontextmanager
from notify import ws_manager
from db import init_db, engine
from sqlmodel import SQLModel, inspect
from pathlib import Path

# Carga base (opcional) y luego el específico por entorno
load_dotenv(find_dotenv(".env", usecwd=True), override=False)
env = os.getenv("ENV", "local").lower()
load_dotenv(find_dotenv(".env.local" if env == "local" else ".env.prod", usecwd=True), override=True)


app = FastAPI()

# --- Static & Uploads ---
BASE_DIR = Path(__file__).resolve().parent

# 1) Resolvemos la ruta de uploads (env en prod, ./uploads en local)
uploads_env = os.getenv("UPLOADS_DIR")
if uploads_env:
    UPLOADS_DIR = Path(uploads_env).resolve()   # En Railway: /uploads
else:
    UPLOADS_DIR = (BASE_DIR.parent / "uploads").resolve()

# 2) Creamos la carpeta antes de montarla (evita RuntimeError en Starlette)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Comandos varios
# source .venv/bin/activate
# rm -rf __pycache__
# -uvicorn main:app --reload


# monta estáticos de tu plantilla admin/pública
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# monta el directorio PERSISTENTE de uploads (volumen en prod)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# --- Sesiones ---
SECRET_KEY = os.getenv("SECRET_KEY")  # ← lee del .env / entorno
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY no está definido(revisa tus .env / variables de entorno)")


# --- Ciclo de vida ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # crea tablas una sola vez al boot
    yield       # no hacemos nada al shutdown (ya migraste a WebSocket)

app.router.lifespan_context = lifespan

app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SECRET_KEY", "dev-fallback-change-me"))



@app.on_event("shutdown")
async def _shutdown():
    pass

# End point vacio para el error que venia de Chrome devtools
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_probe():
    return Response(status_code=204)

# Endpoint de prueba de persistencia del volumen
@app.get("/debug/persist")
def debug_persist():
    p = Path(UPLOADS_DIR) / "marker.txt"
    if not p.exists():
        p.write_text("hello")
        status = "created"
    else:
        status = "exists"
    return {"uploads_dir": UPLOADS_DIR, "marker": str(p), "status": status}

# /debug/db para confirmar la DB
@app.get("/debug/db")
def debug_db():
    url = str(engine.url)
    abs_path = str(engine.url.database) if engine.url.database else None
    insp = inspect(engine)
    return {"engine_url": url, "db_absolute_path": abs_path, "tables": insp.get_table_names()}



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
app.include_router(debug.router)



# ruta de prueba para verificar que la app que corre es esta
@app.get("/ping")
def ping():
    return {"ok": True}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)