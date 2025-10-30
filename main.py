import os, shutil
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Query, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from routers import dashboard, auth, public, products, support, users, master, vendor, share, orders, debug, password_reset
from contextlib import asynccontextmanager
from notify import ws_manager
from db import init_db, engine, get_session
from sqlmodel import SQLModel, inspect, text, Session
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from config import SECRET_KEY, PASSWORD_RESET_TOKEN_MAX_AGE, APP_BASE_URL

app = FastAPI()

# --- Static & Uploads ---
BASE_DIR = Path(__file__).resolve().parent

# 1) Ruta del volumen persistente (Railway: setea UPLOADS_DIR en /uploads)
uploads_env = os.getenv("UPLOADS_DIR")
if uploads_env:
    UPLOADS_DIR = Path(uploads_env).resolve()      # p.ej. /uploads
else:
    UPLOADS_DIR = (BASE_DIR.parent / "uploads").resolve()

# 2) Asegura carpetas antes de montar
(UPLOADS_DIR).mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "vendors").mkdir(parents=True, exist_ok=True)   # logos
(UPLOADS_DIR / "products").mkdir(parents=True, exist_ok=True)  # productos

# 3) Estáticos propios
app.mount("/static", 
    StaticFiles(directory=str(BASE_DIR / "static")), 
    name="static")

# 4) ÚNICO mount público para subir/servir imágenes
app.mount(
    "/uploads", 
    StaticFiles(directory=str(UPLOADS_DIR)), 
    name="uploads")

app.mount(
    "/vendors",
    StaticFiles(directory=str(UPLOADS_DIR / "vendors"), html=False),
    name="vendors-legacy",
)


print("DEBUG MOUNTS -> UPLOADS_DIR=", UPLOADS_DIR)
print("DEBUG MOUNTS -> /uploads =>", str(UPLOADS_DIR))
print("DEBUG MOUNTS -> /products =>", str(UPLOADS_DIR / "products"))

# Comandos varios
# source .venv/bin/activate
# rm -rf __pycache__
# -uvicorn main:app --reload

def _migrate_legacy_static_uploads():
    """
    Compatibilidad: copia /static/uploads/*.*
    -> /uploads/legacy/*.* para que URLs antiguas sigan sirviendo.
    Se ejecuta al boot. Idempotente.
    """
    legacy_src = BASE_DIR / "static" / "uploads"
    legacy_dst = UPLOADS_DIR / "legacy"
    if not legacy_src.exists():
        return
    legacy_dst.mkdir(parents=True, exist_ok=True)
    for p in legacy_src.glob("*.*"):
        target = legacy_dst / p.name
        try:
            if not target.exists() or target.stat().st_size == 0:
                shutil.copy2(p, target)
        except Exception:
            # no interrumpimos el boot por esto
            pass

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# --- Ciclo de vida ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # crea tablas una sola vez al boot
    _migrate_legacy_static_uploads()   # ← ejecuta la copia de compatibilidad
    yield       # no hacemos nada al shutdown (ya migraste a WebSocket)

app.router.lifespan_context = lifespan


app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

@app.get("/debug/ls")
def debug_ls(slug: str = Query(...)):
    prods_dir = (UPLOADS_DIR / "products" / slug)
    vend_dir  = (UPLOADS_DIR / "vendors"  / slug)
    return {
        "products_path": str(prods_dir),
        "products_files": sorted([p.name for p in prods_dir.glob("*")]) if prods_dir.exists() else [],
        "vendors_path": str(vend_dir),
        "vendors_files": sorted([p.name for p in vend_dir.glob("*")]) if vend_dir.exists() else [],
    }

@app.post("/debug/migrate-urls")
def migrate_urls(session: Session = Depends(get_session)):
    # TODO: protege esto (p.ej. valida request.session["user_id"] es admin)

    res = {}

    def run(sql):
        session.exec(text(sql))

    # /products -> /uploads/products
    run("""
    UPDATE products
       SET image_url = REPLACE(image_url, '/products/', '/uploads/products/')
     WHERE image_url LIKE '/products/%';
    """)
    res["products_fixed"] = session.exec(text("""
        SELECT COUNT(*) FROM products WHERE image_url LIKE '/products/%'
    """)).first()[0]

    # /vendors -> /uploads/vendors
    run("""
    UPDATE vendor_brandings
       SET logo_url = REPLACE(logo_url, '/vendors/', '/uploads/vendors/')
     WHERE logo_url LIKE '/vendors/%';
    """)
    res["logos_fixed"] = session.exec(text("""
        SELECT COUNT(*) FROM vendor_brandings WHERE logo_url LIKE '/vendors/%'
    """)).first()[0]

    session.commit()
    return {"ok": True, **res}

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
app.include_router(password_reset.router)



# ruta de prueba para verificar que la app que corre es esta
@app.get("/ping")
def ping():
    return {"ok": True}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)