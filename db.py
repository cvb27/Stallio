import os
from typing import Generator
from pathlib import Path

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine.url import make_url


# ============================================================
# 1) Leer y normalizar DATABASE_URL
# ============================================================

# En Railway será algo tipo:
# DATABASE_URL="postgresql+psycopg2://user:pass@host:port/db"
# Por defecto en local usamos SQLite.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Compatibilidad: convertir postgres:// -> postgresql+psycopg2://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg2://", 1
    )
# Parseamos la URL para detectar tipo de motor (sqlite/postgres/etc.)
url = make_url(DATABASE_URL)


# ============================================================
# 2) Ajustes especiales para SQLite
# ============================================================

connect_args = {}
if url.drivername.startswith("sqlite"):
    # Necesario para SQLite + threads (FastAPI)
    connect_args = {"check_same_thread": False}

    # Crear el directorio del archivo SQLite si no existe
    if url.database:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)

# ============================================================
# 3) Crear el engine global
# ============================================================
# Crea el engine global que usará toda la app y Alembic

engine = create_engine(
    DATABASE_URL,
    echo=False,           # pon True si quieres ver el SQL en consola
    pool_pre_ping=True,   # ayuda a evitar conexiones muertas
    connect_args=connect_args,
)

# Factory de sesiones (para usar en dependencias de FastAPI, scripts, etc.)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# ============================================================
# 4) Dependencia típica de FastAPI
# ============================================================

def get_session():
    """
    Dependencia típica de FastAPI.
    Uso:

    @router.get("/algo")
    def algo(db: Session = Depends(get_session)):
        ...
    """
    with SessionLocal() as session:
        yield session

# ============================================================
# 5) Helper opcional para crear tablas sin Alembic
#    (EN PRODUCCIÓN: usar SIEMPRE migraciones Alembic)
# ============================================================

def init_db() -> None:
    """
    Crea las tablas a partir de los modelos de SQLModel.

    ⚠️ IMPORTANTE:
    - En producción, usa Alembic (migraciones) en lugar de esta función.
    - Puedes usarla manualmente en desarrollo/local si quieres
      levantar rápido una base nueva.

    Ejemplo manual:

        from models import *
        from db import init_db
        init_db()
    """
    import models # noqa: F401,F403  (asegura que se carguen todos los modelos)
    SQLModel.metadata.create_all(bind=engine)
