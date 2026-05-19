"""Minute-pack store views."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_security import current_user
from sqlalchemy import and_

from ...actions import register_checkout_account
from ...extensions import db
from ...log import get_logger
from ...models import MinutePack, Order, OrderItem, OrderItemType, OrderStatus
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
    is_authenticated_user = bool(
        current_user and getattr(current_user, "is_authenticated", False)
    )

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("comprar_minutos POST: pack_id=%s payment_method=%r", pack_id, payment_method)

        if payment_method not in ("flow", "khipu"):
            logger.warning("Invalid payment method %r for pack_id=%s", payment_method, pack_id)
            flash(_("Método de pago no válido."), "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_id=pack_id))

        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        create_account = request.form.get("create_account") == "on"

        if not email:
            logger.debug("comprar_minutos: missing email for pack_id=%s", pack_id)
            flash(_("El email es obligatorio."), "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_id=pack_id))

        duplicate_cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
        duplicate_filter = (
            and_(
                OrderItem.item_type == OrderItemType.MINUTE_PACK,
                OrderItem.item_id == pack.id,
            )
        )
        duplicate_query = (
            Order.query.filter(
                Order.status == OrderStatus.PENDING,
                Order.provider == payment_method,
                Order.amount == pack.price,
                Order.shipping_email == email,
                Order.created_at >= duplicate_cutoff,
                Order.items.any(duplicate_filter),
            )
            .order_by(Order.created_at.desc())
        )
        if is_authenticated_user:
            duplicate_query = duplicate_query.filter(Order.user_id == current_user.id)
        else:
            duplicate_query = duplicate_query.filter(Order.user_id.is_(None))

        existing_order = duplicate_query.first()
        if existing_order:
            logger.info(
                "comprar_minutos: prevented duplicate order creation for pack_id=%s existing_order=%s user=%s email=%r",
                pack.id,
                existing_order.id,
                existing_order.user_id,
                email,
            )
            flash(
                _("Ya estamos procesando tu compra. Evita hacer clic repetido en el botón de pago."),
                "info",
            )
            return redirect(url_for("pagos.orden_estado", order_id=existing_order.id))

        order = Order(
            amount=Decimal(str(pack.price)),
            currency=pack.currency,
            provider=payment_method,
            email=email,
            shipping_phone=phone or None,
        )
        if is_authenticated_user:
            order.user_id = current_user.id
        elif create_account:
            try:
                checkout_user, created = register_checkout_account(
                    email=email,
                    phone=phone,
                )
            except ValueError as exc:
                if str(exc) == "missing_phone":
                    flash(
                        _("Para crear tu cuenta debes ingresar un teléfono."),
                        "danger",
                    )
                else:
                    flash(
                        _(
                            "Ingresa un teléfono válido (solo dígitos, sin +, entre 10 y 13 dígitos)."
                        ),
                        "danger",
                    )
                return redirect(url_for("minutos.comprar_minutos", pack_id=pack_id))

            order.user_id = checkout_user.id
            if created:
                flash(
                    _(
                        "Cuenta creada. Te enviamos un correo de bienvenida y confirmación. "
                        "Cuando confirmes tu email, ingresa desde el acceso sin contraseña."
                    ),
                    "success",
                )
            else:
                flash(
                    _(
                        "Ya existe una cuenta con ese email. Puedes ingresar con acceso sin contraseña."
                    ),
                    "info",
                )

        db.session.add(order)
        db.session.flush()

        # Resolve Firenze client_id as early as possible.
        from ...firenze import search_client as _firenze_search

        if is_authenticated_user and current_user.firenze_client_id:
            order.firenze_client_id = current_user.firenze_client_id
        else:
            try:
                firenze_phone = (
                    (current_user.username or "").strip()
                    if is_authenticated_user
                    else phone
                )
                firenze_id = _firenze_search(email=email, phone=firenze_phone or None)
                if firenze_id is not None:
                    order.firenze_client_id = firenze_id
                    if is_authenticated_user and not current_user.firenze_client_id:
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
            unit_price=Decimal(str(pack.price)),
            currency=pack.currency,
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
    prefilled_shipping_phone = ""
    if is_authenticated_user:
        preferred = current_user.preferred_payment
        prefilled_email = current_user.email or ""
        prefilled_phone = current_user.username or ""
        prefilled_shipping_phone = current_user.phone or ""

    return render_template(
        "tienda/comprar_minutos.html",
        pack=pack,
        preferred=preferred,
        prefilled_email=prefilled_email,
        prefilled_phone=prefilled_phone,
        prefilled_shipping_phone=prefilled_shipping_phone,
        cart_count=len(_get_cart()),
    )
