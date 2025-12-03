

"""
Script de una sola vez para crear la tabla Review en la base de datos.

Uso:
  python3 scripts/init_reviews.py
"""

from sqlmodel import SQLModel
from db import engine
from models import Review  # importa el modelo para que quede en el metadata


def main():
    # create_all creará cualquier tabla que aún no exista
    SQLModel.metadata.create_all(engine)
    print("OK: tablas creadas/actualizadas (incluida 'review').")


if __name__ == "__main__":
    main()
