from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from pydantic import EmailStr
from copy import deepcopy


DEFAULT_BRANDING_SETTINGS: Dict[str, Any] = {
    "tagline": "",
    "primary_color": "#111827",
    "accent_color": "#2563eb",
    "contact_email": "",
    "whatsapp": "",
    "instagram": "",
    "hero_image_url": "",
    "logo_url": "", 
    "about": "",
    "location": "",
}


# Modelo de usuario para la implementacion del Signup.
class User(SQLModel, table=True):
    __tablename__ = "users"  # nombre explícito para evitar choques
    id: Optional[int] = Field(default=None, primary_key=True)
    email: EmailStr = Field(index=True, unique=True)
    name: Optional[str] = Field(default=None, max_length=120)
    role: str = Field(default="vendor", max_length=20)   # "vendor" | "admin"
    is_active: bool = Field(default=True)               # alta/baja
    salt: str                                           # para hashear contraseña
    password_hash: str                                  # hash estable
    slug: str = Field(index=True, unique=True, default="")  # /u/<slug>
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    price: float = 0.0
    stock: int = 0
    category: Optional[str] = None  # DEPRECATED
    image_url: Optional[str] = None
    owner_id: int = Field(index=True)  # ← vendedor dueño
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    


class PaymentReport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    qty: int = 1
    payer_name: Optional[str] = None
    phone: Optional[str] = None
    amount_type: str  # "50" o "100"
    amount: float 
    owner_id: int = Field(index=True) # dueño (vendor)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

 # tabla de archivo para órdenes despachadas
class DispatchedOrder(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    payment_report_id: int = Field(index=True, unique=True)  # cada report solo puede despacharse una vez
    owner_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class VendorBranding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True, unique=True)  # 1 perfil por vendor
    slug: str = Field(index=True, unique=True)  # <- IMPORTANTE
    display_name: str = Field(default="Mi Tienda")
    settings: Dict[str, Any] = Field(                     # <-- IMPORTANTE
        sa_column=Column(JSON, nullable=False),
        default_factory=lambda: deepcopy(DEFAULT_BRANDING_SETTINGS),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
