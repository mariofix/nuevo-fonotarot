"""Shared helpers for tienda sub-blueprints."""

from decimal import Decimal
from urllib.parse import urlparse

from flask import flash, redirect, request, session
from flask_babel import _

from ..log import get_logger
from ..models import Order
from ..notifications import send_new_order_admin_email

logger = get_logger(__name__)

CART_SESSION_KEY = "tienda_cart"


def _safe_next(default: str) -> str:
    """Return a safe internal redirect URL from the POST ``next`` parameter.

    External URLs and absolute URLs with a host are rejected and *default*
    is returned instead, preventing open-redirect attacks.
    """
    raw = request.form.get("next", "").strip()
    if not raw:
        return default
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return default
    return raw


def _get_cart() -> list:
    """Return the current cart from the session (list of item dicts)."""
    return session.get(CART_SESSION_KEY, [])


def _save_cart(cart: list) -> None:
    session[CART_SESSION_KEY] = cart
    session.modified = True


def _cart_total(cart: list) -> Decimal:
    return sum(
        (Decimal(str(item["unit_price"])) * item["quantity"] for item in cart),
        Decimal(0),
    )


def create_payment_and_redirect(
    order: Order,
    payment_method: str,
    email: str,
    error_redirect: str,
) -> object:
    """Initiate a checkout session via flask-merchants and redirect to the provider.

    Args:
        order: The Order to pay for.
        payment_method: Provider key ("flow" or "khipu").
        email: Customer email for the checkout session.
        error_redirect: URL to redirect to if payment initiation fails,
            so the user lands back on the relevant page instead of the
            generic cart checkout.

    Returns:
        A Flask redirect response.
    """
    logger.debug(
        "Initiating checkout via %s for order=%s amount=%s email=%r",
        payment_method,
        order.id,
        order.amount,
        email,
    )
    try:
        redirect_url = order.initiate_payment(payment_method, email)
    except Exception as exc:
        logger.error("Payment creation error (%s): %s", payment_method, exc, exc_info=True)
        flash(_("Error al conectar con el proveedor de pago. Intenta más tarde."), "danger")
        return redirect(error_redirect)

    logger.info(
        "Checkout session created: order=%s provider=%s transaction_id=%s",
        order.id,
        payment_method,
        order.transaction_id,
    )
    send_new_order_admin_email(order)
    return redirect(redirect_url)
