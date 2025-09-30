import os
from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


# Lee de entorno (ya cargado por main.py)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Compatibilidad: postgres:// -> postgresql+psycopg2:// (por si algún día migras)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    
# 2) Para SQLite: asegúrate de que existe el directorio del archivo
connect_args = {}
url = make_url(DATABASE_URL)
if url.drivername.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    if url.database:  # ruta del archivo
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        
# 3) Crea el engine UNA sola vez
engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
)

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

def init_db():
    """
    Crea las tablas si no existen. 
    - En SQLite es útil en desarrollo.
    - En PostgreSQL (Railway) no hace daño; si usas Alembic, puedes dejarla como 'pass'
      o mantener create_all (no borra ni sobreescribe).
    """
    try:
        # Si prefieres que en Postgres no haga nada y usar sólo Alembic:
        # if not settings.DATABASE_URL.startswith("sqlite"):
        #     return
        SQLModel.metadata.create_all(engine)
    except Exception as e:
        # Evita tumbar el arranque si hay una race condition; puedes loguearlo si quieres
        print(f"[init_db] warning: {e}")




""""
# Ruta ABSOLUTA del archivo de base de datos (evita “dos archivos” según desde dónde arranque uvicorn)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.sqlite3")   # <- quedará en /.../App_pedidos/data.sqlite3
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(

    DATABASE_URL,
    connect_args={"check_same_thread": False},  # necesario para SQLite con múltiples hilos
    echo=False, 
)

SQLModel.metadata.create_all(engine)

def init_db() -> None:
    # IMPORTA LOS MODELOS ANTES DE CREAR TABLAS
    from models import Product, PaymentReport, DispatchedOrder  # noqa: F401
    SQLModel.metadata.create_all(engine)

def get_session():
       Dependency de FastAPI: inyecta una sesión de DB por request.
    with Session(engine) as session:
        yield session
"""