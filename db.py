import os
from sqlmodel import SQLModel, create_engine, Session


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
    """Dependency de FastAPI: inyecta una sesión de DB por request."""
    with Session(engine) as session:
        yield session