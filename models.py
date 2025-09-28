from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, String, UniqueConstraint
from sqlalchemy import JSON  # JSON nativo de SQLAlchemy (para SQLite lo mapea a TEXT)
from pydantic import EmailStr

# ----------------------------
# Helpers
# ----------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

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

# ----------------------------
# Models
# ----------------------------

class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    email: EmailStr = Field(sa_column=Column(String(255), nullable=False, index=True))
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    name: Optional[str] = Field(default=None, sa_column=Column(String(120)))
    is_active: bool = Field(default=True, nullable=False)
    is_admin: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(default_factory=now_utc, nullable=False)
    updated_at: datetime = Field(default_factory=now_utc, nullable=False)
    slug: str = Field(sa_column=Column(String(120), nullable=False, index=True))
    role: str = Field(default="vendor", sa_column=Column(String(20), nullable=False))


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    name: str = Field(sa_column=Column(String(160), nullable=False))
    price: float
    description: Optional[str] = Field(default=None, sa_column=Column(String(1000)))
    image_url: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=now_utc, nullable=False)
    updated_at: datetime = Field(default_factory=now_utc, nullable=False)

    # explícitos para que queden como columnas
    stock: int = Field(default=0, nullable=False)
    category: Optional[str] = Field(default=None, sa_column=Column(String(120)))


class PaymentReport(SQLModel, table=True):
    __tablename__ = "payment_reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True, nullable=False)
    qty: int = Field(default=1, nullable=False)
    payer_name: Optional[str] = Field(default=None, sa_column=Column(String(160)))
    phone: Optional[str] = Field(default=None, sa_column=Column(String(40)))
    amount_type: str = Field(sa_column=Column(String(8), nullable=False))  # "50" o "100"
    amount: float
    owner_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    created_at: datetime = Field(default_factory=now_utc, nullable=False)


class DispatchedOrder(SQLModel, table=True):
    __tablename__ = "dispatched_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    payment_report_id: int = Field(
        foreign_key="payment_reports.id", index=True, unique=True, nullable=False
    )
    owner_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    created_at: datetime = Field(default_factory=now_utc, nullable=False)


class VendorBranding(SQLModel, table=True):
    __tablename__ = "vendor_brandings"
    __table_args__ = (UniqueConstraint("slug", name="uq_branding_slug"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    slug: str = Field(sa_column=Column(String(120), nullable=False, index=True))
    display_name: str = Field(sa_column=Column(String(120), nullable=False))
    # JSON con default dict
    settings: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    logo_url: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    created_at: datetime = Field(default_factory=now_utc, nullable=False)
    updated_at: datetime = Field(default_factory=now_utc, nullable=False)


class PasswordReset(SQLModel, table=True):
    __tablename__ = "password_resets"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, nullable=False)
    token_hash: str = Field(sa_column=Column(String(128), index=True, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, nullable=False)
    expires_at: datetime = Field(nullable=False)
    used_at: Optional[datetime] = None
