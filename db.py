import os
from typing import Generator
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from pydantic_settings import BaseSettings

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Compatibilidad: postgres:// -> postgresql+psycopg2://
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg2://", 1)

# SQLite requiere flag especial para threads
engine_kwargs = dict(pool_pre_ping=True, future=True)
if DB_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine("sqlite:///./app.db", echo=False)

def get_session():
    with Session(engine) as session:
        yield session

class Settings(BaseSettings):
    # Para local usa SQLite por defecto; en Railway define DATABASE_URL
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

    class Config:
        env_file = ".env"

settings = Settings()

# Conexión: SQLite requiere un connect_args especial
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
)

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