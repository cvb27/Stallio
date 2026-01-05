
import os
import stripe
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from sqlmodel import Session, select
from templates_engine import templates

from db import get_session
from models import User, VendorBranding  # ajusta si tu modelo está en otro lugar


router = APIRouter()

# ==========================
# Config Stripe
# ==========================
# Recomendado: STRIPE_SECRET_KEY en env (local y Railway)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Price ID del plan mensual (lo creas en Stripe Dashboard)
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")

# Webhook secret (Stripe -> tu app)
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Base URL pública de tu app en producción (Railway)
# Ej: https://stallio.up.railway.app
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")


# ==========================
# Helpers
# ==========================
def _require_login(request: Request) -> int:
    """Devuelve user_id de la sesión o lanza 401."""
    owner_id = request.session.get("user_id")
    if not owner_id:
        raise HTTPException(status_code=401, detail="No autenticado")
    return int(owner_id)

def _require_vendor_by_slug(session: Session, slug: str, owner_id: int) -> User:
    """
    Busca el vendor por slug y valida que sea el mismo usuario logueado.
    Mantiene tu patrón de seguridad actual.
    """
    vendor = session.exec(select(User).where(User.slug == slug)).first()
    if not vendor or int(vendor.id) != int(owner_id):
        raise HTTPException(status_code=403, detail="No autorizado")
    return vendor

def _get_or_create_branding(session: Session, owner_id: int) -> VendorBranding:
    """
    Obtiene branding del owner. Si tu proyecto ya tiene get_branding_by_owner(),
    úsala aquí en vez de reimplementar.
    """
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.owner_id == owner_id)
    ).first()
    if not branding:
        # Si no existe, creamos lo mínimo para que haya slug.
        user = session.exec(select(User).where(User.id == owner_id)).first()
        base_slug = user.slug if user and getattr(user, "slug", None) else f"tienda-{owner_id}"

        # Si tú ya tienes _unique_slug(...) úsalo.
        branding = VendorBranding(
            owner_id=owner_id,
            slug=base_slug,
            display_name="Mi Tienda",
            settings={},
        )
        session.add(branding)
        session.commit()
        session.refresh(branding)

    if branding.settings is None:
        branding.settings = {}
    return branding

def _set_subscription_status(session: Session, owner_id: int, status: str, customer_id: str | None = None, subscription_id: str | None = None) -> None:
    """
    Guarda el estado de la suscripción en VendorBranding.settings de forma segura.
    """
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.owner_id == int(owner_id))
    ).first()
    if not branding:
        return

    settings = branding.settings or {}
    settings["subscription_status"] = status

    if customer_id:
        settings["stripe_customer_id"] = customer_id
    if subscription_id:
        settings["stripe_subscription_id"] = subscription_id

    branding.settings = settings
    session.add(branding)
    session.commit()


# ==========================
# Rutas
# ==========================

@router.get("/admin/billing")
async def billing_shortcut(request: Request, session: Session = Depends(get_session)):
    """
    Shortcut: /admin/billing -> /admin/{slug}/billing
    Similar a tu support_shortcut.
    """
    owner_id = request.session.get("user_id")
    if not owner_id:
        return RedirectResponse("/login", status_code=302)

    user = session.get(User, int(owner_id))
    if not user:
        return RedirectResponse("/login", status_code=302)

    return RedirectResponse(f"/admin/{user.slug}/billing", status_code=302)


@router.get("/admin/{slug}/billing", response_class=HTMLResponse)
async def billing_page(slug: str, request: Request, session: Session = Depends(get_session)):
    """
    Página de suscripción:
    - muestra status (si existe)
    - botón para pagar (Checkout)
    - botón para administrar (Customer Portal)
    """
    owner_id = _require_login(request)
    vendor = _require_vendor_by_slug(session, slug, owner_id)
    branding = session.exec(
        select(VendorBranding).where(VendorBranding.owner_id == owner_id)
    ).first()

    if not branding:
        raise HTTPException(
            status_code=400,
            detail="Branding no encontrado. Completa la configuración de tu tienda."
    )
    print(
    "[BILLING PAGE]",
    "owner_id=", owner_id,
    "branding_id=", branding.id,
    "settings=", branding.settings
)

    settings = branding.settings or {}
    sub_status = (settings.get("subscription_status") or "inactive").strip()
    stripe_customer_id = settings.get("stripe_customer_id")
    stripe_subscription_id = settings.get("stripe_subscription_id")

    ctx = {
        "request": request,
        "vendor": vendor,  # requerido por admin/layout.html
        "branding": branding,
        "subscription_status": sub_status,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
    }
    return templates.TemplateResponse("admin/billing.html", ctx)



@router.post("/admin/{slug}/billing/checkout")
async def billing_checkout(slug: str, request: Request, session: Session = Depends(get_session)):
    """
    Crea una Stripe Checkout Session en modo subscription.
    El usuario paga con tarjeta (Stripe checkout).
    """
    owner_id = _require_login(request)
    vendor = _require_vendor_by_slug(session, slug, owner_id)
    branding = _get_or_create_branding(session, owner_id)

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe no configurado (STRIPE_SECRET_KEY).")
    if not STRIPE_PRICE_ID:
        raise HTTPException(status_code=500, detail="Plan no configurado (STRIPE_PRICE_ID).")

    # URLs de retorno
    success_url = f"{PUBLIC_BASE_URL}/admin/{quote(vendor.slug)}/billing?success=1"
    cancel_url  = f"{PUBLIC_BASE_URL}/admin/{quote(vendor.slug)}/billing?canceled=1"

    settings = branding.settings or {}

    # Si ya tenemos customer_id, lo reutilizamos
    stripe_customer_id = settings.get("stripe_customer_id")

    # Crear checkout session
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=stripe_customer_id,  # puede ser None
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        # Guarda contexto para el webhook
        metadata={
            "owner_id": str(owner_id),
            "vendor_slug": vendor.slug,
        },
    )

    # Redirige al checkout de Stripe
    return RedirectResponse(checkout.url, status_code=303)


@router.post("/admin/{slug}/billing/portal")
async def billing_portal(slug: str, request: Request, session: Session = Depends(get_session)):
    """
    Abre el Customer Portal para:
    - cambiar tarjeta
    - ver facturas
    - cancelar
    - actualizar datos
    """
    owner_id = _require_login(request)
    vendor = _require_vendor_by_slug(session, slug, owner_id)
    branding = _get_or_create_branding(session, owner_id)

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe no configurado (STRIPE_SECRET_KEY).")

    settings = branding.settings or {}
    stripe_customer_id = settings.get("stripe_customer_id")
    if not stripe_customer_id:
        # Si no hay customer todavía, mandamos a checkout primero
        return RedirectResponse(f"/admin/{vendor.slug}/billing?need_checkout=1", status_code=302)

    return_url = f"{PUBLIC_BASE_URL}/admin/{quote(vendor.slug)}/billing"

    portal = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )

    return RedirectResponse(portal.url, status_code=303)


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    """
    Webhook endpoint para sincronizar estado de suscripción.
    IMPORTANTE: Debe ser accesible públicamente en Railway.
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    if not STRIPE_WEBHOOK_SECRET:
        # En dev local podrías permitirlo, pero en prod mejor exigirlo
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET no configurado.")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception:
        return PlainTextResponse("Invalid signature", status_code=400)
    
    etype = event["type"]
    data = event["data"]["object"]

    # ==========================
    # 1) Checkout completado -> activar (tiene metadata owner_id)
    # ==========================

    if etype == "checkout.session.completed":
        owner_id = data.get("metadata", {}).get("owner_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")

        print("[WEBHOOK] checkout completed owner=", owner_id, "customer=", customer_id)

        # Solo si viene owner_id (debe venir por tu metadata)
        if owner_id:
            _set_subscription_status(
                session=session,
                owner_id=int(owner_id),
                status="active",
                customer_id=customer_id,
                subscription_id=subscription_id,
            )

    # ==========================
    # 2) Eventos de suscripción -> sincronizar status por customer_id
    # ==========================

    if etype in (
        "customer.subscription.created",
        "customer.subscription.updated", 
        "customer.subscription.deleted"
    ):
        subscription_id = data.get("id")
        customer_id = data.get("customer")
        status = (data.get("status") or "inactive").strip()

        print("[WEBHOOK] sub event", etype, "customer=", customer_id, "status=", status)

        # Si no hay customer_id, no podemos mapear
        if not customer_id:
            return PlainTextResponse("ok", status_code=200)
        
        # Fallback universal (funciona en SQLite y Postgres):
        branding = session.exec(
            select(VendorBranding)
            .where(VendorBranding.settings["stripe_customer_id"].as_string() == customer_id)
        ).first()

        # Fallback para SQLite / JSON simple
        branding = None
        all_brandings = session.exec(select(VendorBranding)).all()
        for b in all_brandings:
            s = b.settings or {}
            if s.get("stripe_customer_id") == customer_id:
                branding = b
                break

        if branding:
            _set_subscription_status(
                session=session,
                owner_id=int(branding.owner_id),
                status=status,
                customer_id=customer_id,
                subscription_id=subscription_id,
        )
    return PlainTextResponse("ok", status_code=200)
