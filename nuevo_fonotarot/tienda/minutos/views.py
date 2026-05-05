"""Minute-pack store views."""

from flask import flash, redirect, render_template, request, url_for
from flask_security import current_user

from ...extensions import db
from ...log import get_logger
from ...models import MinutePack, Order, OrderItem, OrderItemType
from ..utils import _get_cart, create_payment_and_redirect
from . import minutos_bp

logger = get_logger(__name__)


@minutos_bp.route("/")
def index():
    """Prepaid tarot minute packs listing."""
    packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    return render_template("tienda/minutos.html", packs=packs, cart_count=len(_get_cart()))


@minutos_bp.route("/<int:pack_id>/comprar", methods=["GET", "POST"])
def comprar_minutos(pack_id: int):
    """Fast checkout for a single minute pack.

    GET  → show the checkout form (payment method + contact details).
    POST → create order + redirect to payment gateway.

    Three customer variants:
    - Anonymous: must supply email on every purchase.
    - Known (authenticated, no physical profile): email pre-filled.
    - Physical (authenticated, full profile): all data pre-filled.
    """
    pack = MinutePack.query.filter_by(id=pack_id, is_active=True).first_or_404()

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("comprar_minutos POST: pack_id=%s payment_method=%r", pack_id, payment_method)

        if payment_method not in ("flow", "khipu"):
            logger.warning("Invalid payment method %r for pack_id=%s", payment_method, pack_id)
            flash("Método de pago no válido.", "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_id=pack_id))

        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        if not email:
            logger.debug("comprar_minutos: missing email for pack_id=%s", pack_id)
            flash("El email es obligatorio.", "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_id=pack_id))

        order = Order(
            total=pack.price,
            provider=payment_method,
            shipping_email=email,
            shipping_phone=phone,
        )
        if current_user.is_authenticated:
            order.user_id = current_user.id

        db.session.add(order)
        db.session.flush()

        # Resolve Firenze client_id as early as possible.
        from ...firenze import search_client as _firenze_search

        if current_user.is_authenticated and current_user.firenze_client_id:
            order.firenze_client_id = current_user.firenze_client_id
        else:
            try:
                firenze_id = _firenze_search(email=email, phone=phone or None)
                if firenze_id is not None:
                    order.firenze_client_id = firenze_id
                    if current_user.is_authenticated and not current_user.firenze_client_id:
                        current_user.firenze_client_id = firenze_id
            except Exception:
                logger.exception(
                    "comprar_minutos: Firenze search_client or user update failed for order=%s",
                    order.id,
                )

        item = OrderItem(
            order_id=order.id,
            item_type=OrderItemType.MINUTE_PACK,
            item_id=pack.id,
            name=f"{pack.minutes} minutos de tarot",
            quantity=1,
            unit_price=pack.price,
        )
        db.session.add(item)
        db.session.commit()

        logger.info(
            "Order created: order=%s pack_id=%s minutes=%s price=%s user=%s email=%r",
            order.id,
            pack.id,
            pack.minutes,
            pack.price,
            order.user_id,
            email,
        )

        return create_payment_and_redirect(
            order,
            payment_method,
            email,
            error_redirect=url_for("minutos.comprar_minutos", pack_id=pack_id),
        )

    # GET — pre-fill from authenticated user profile
    preferred = None
    prefilled_email = ""
    prefilled_phone = ""
    if current_user.is_authenticated:
        preferred = current_user.preferred_payment
        prefilled_email = current_user.email or ""
        prefilled_phone = current_user.username or ""

    return render_template(
        "tienda/comprar_minutos.html",
        pack=pack,
        preferred=preferred,
        prefilled_email=prefilled_email,
        prefilled_phone=prefilled_phone,
        cart_count=len(_get_cart()),
    )
