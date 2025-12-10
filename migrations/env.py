from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# --------------------------------------------------------
# IMPORTA EL ENGINE Y LOS MODELOS EXACTAMENTE COMO EN TU APP
# --------------------------------------------------------

# Asegura que Alembic pueda importar tus módulos
sys.path.append(os.path.abspath("."))  


# 🔹 Importa tu engine y tus modelos
from db import engine  # <-- tu engine real
import models  # <-- importa TODOS los modelos (importante)

# --------------------------------------------------------
# CONFIGURACIÓN BASE DE ALEMBIC
# --------------------------------------------------------
# Esta variable la usa Alembic internamente

config = context.config

# Configuración de logging (opcional pero recomendable)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata = modelos de SQLModel
target_metadata = SQLModel.metadata

# --------------------------------------------------------
# Obtiene la DATABASE_URL desde variables de entorno
# (Railway, Docker, máquina local, etc.)
# --------------------------------------------------------

def get_url():
    return os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# --------------------------------------------------------
# MODO OFFLINE (genera SQL sin conectarse a la DB)
# --------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Aquí tomamos el URL desde el engine que ya usa tu app.
    """
    url = str(engine.url)

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # importante para detectar cambios
    )

    with context.begin_transaction():
        context.run_migrations()

# --------------------------------------------------------
# MODO ONLINE (se conecta a la base real)
# --------------------------------------------------------

def run_migrations_online() -> None:
    """
    Es el modo que usarás normalmente.
    OJO: ignoramos el sqlalchemy.url del alembic.ini
    """

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

# --------------------------------------------------------
# Ejecutar modo correcto
# --------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()