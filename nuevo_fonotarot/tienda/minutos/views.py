"""Minute-pack store views."""

from datetime import datetime, timedelta
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_security import current_user
from sqlalchemy import and_

from ...actions import register_checkout_account
from ...extensions import db
from ...log import get_logger
from ...models import DiscountCode, MinutePack, Order, OrderItem, OrderItemType, OrderStatus
from ..utils import _get_cart, apply_discount, create_payment_and_redirect, find_auto_discount_code_for_user
from . import minutos_bp

logger = get_logger(__name__)


@minutos_bp.route("/")
def index():
    """Prepaid tarot minute packs listing."""
    packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    return render_template("tienda/minutos.html", packs=packs, cart_count=len(_get_cart()))


@minutos_bp.route("/<pack_slug>/comprar", methods=["GET", "POST"])  # type: ignore
def comprar_minutos(pack_slug: str):
    """Fast checkout for a single minute pack.

    GET  → show the checkout form (payment method + contact details).
    POST → create order + redirect to payment gateway.

    Three customer variants:
    - Anonymous: must supply email on every purchase.
    - Known (authenticated, no physical profile): email pre-filled.
    - Physical (authenticated, full profile): all data pre-filled.
    """
    pack = MinutePack.query.filter_by(slug=pack_slug, is_active=True).first_or_404()
    is_authenticated_user = bool(current_user and getattr(current_user, "is_authenticated", False))

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("comprar_minutos POST: pack_slug=%s payment_method=%r", pack_slug, payment_method)

        if payment_method not in ("flow", "khipu"):
            logger.warning("Invalid payment method %r for pack_slug=%s", payment_method, pack_slug)
            flash(_("Método de pago no válido."), "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))

        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        create_account = request.form.get("create_account") == "on"

        if not email:
            logger.debug("comprar_minutos: missing email for pack_slug=%s", pack_slug)
            flash(_("El email es obligatorio."), "danger")
            return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))

        # Check for discount code or auto-applied rule-based promotion.
        discount_code_str = request.form.get("discount_code", "").strip()
        discount_obj = None
        discount_amount = Decimal("0")
        if discount_code_str:
            discount_obj = DiscountCode.query.filter_by(code=discount_code_str).first()
            if not discount_obj or not discount_obj.is_valid():
                flash(_("Código de descuento inválido o expirado."), "danger")
                return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))

            if discount_obj.auto_apply_criteria and not discount_obj.user_meets_auto_apply_criteria(
                current_user if is_authenticated_user else None
            ):
                flash(_("El código de descuento no cumple las condiciones de uso."), "danger")
                return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))

            discount_amount = apply_discount(pack.price, pack.currency, discount_obj)
            if discount_amount <= 0:
                flash(_("El código de descuento no es aplicable a este producto."), "danger")
                return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))
        elif is_authenticated_user:
            auto_discount = find_auto_discount_code_for_user(current_user, pack.price, pack.currency)
            if auto_discount is not None:
                discount_obj = auto_discount
                discount_amount = apply_discount(pack.price, pack.currency, discount_obj)
                flash(_("Se aplicó automáticamente el código %(code)s.", code=discount_obj.code), "success")

        duplicate_cutoff = datetime.now() - timedelta(minutes=2)
        duplicate_filter = and_(
            OrderItem.item_type == OrderItemType.MINUTE_PACK,
            OrderItem.item_id == pack.id,
        )
        duplicate_query = Order.query.filter(
            Order.status == OrderStatus.PENDING,
            Order.provider == payment_method,
            Order.amount == pack.price,
            Order.shipping_email == email,
            Order.created_at >= duplicate_cutoff,
            Order.items.any(duplicate_filter),
        ).order_by(Order.created_at.desc())
        if is_authenticated_user:
            duplicate_query = duplicate_query.filter(Order.user_id == current_user.id)
        else:
            duplicate_query = duplicate_query.filter(Order.user_id.is_(None))

        existing_order = duplicate_query.first()
        if existing_order:
            logger.info(
                "comprar_minutos: prevented duplicate order creation for pack_id=%s existing_order=%s "
                "user=%s email=%r",
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

        final_amount = max(Decimal("0"), pack.price - discount_amount)

        order = Order(
            amount=final_amount,
            currency=pack.currency,
            provider=payment_method,
            email=email,
            shipping_phone=phone or None,
            discount_code_id=discount_obj.id if discount_obj else None,
            applied_discount_code=discount_obj.code if discount_obj else None,
            discount_amount=discount_amount if discount_amount > 0 else None,
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
                        _("Ingresa un teléfono válido (solo dígitos, sin +, entre 10 y 13 dígitos)."),
                        "danger",
                    )
                return redirect(url_for("minutos.comprar_minutos", pack_slug=pack_slug))

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
                    _("Ya existe una cuenta con ese email. Puedes ingresar con acceso sin contraseña."),
                    "info",
                )

        if discount_obj:
            DiscountCode.query.filter_by(id=discount_obj.id).update(
                {DiscountCode.uses_count: DiscountCode.uses_count + 1}
            )

        db.session.add(order)
        db.session.flush()

        # Resolve Firenze client_id as early as possible.
        from ...firenze import search_client as _firenze_search

        if is_authenticated_user and current_user.firenze_client_id:
            order.firenze_client_id = current_user.firenze_client_id
        else:
            try:
                firenze_phone = (current_user.username or "").strip() if is_authenticated_user else phone
                firenze_id = _firenze_search(email=email, ani=firenze_phone or None)
                if firenze_id is not None:
                    order.firenze_client_id = firenze_id
                    if is_authenticated_user and not current_user.firenze_client_id:
                        current_user.firenze_client_id = firenze_id
            except Exception:
                logger.exception(f"comprar_minutos: Firenze search_client or user update failed for {order.id=}")

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
            "Order created via Checkout: order=%s pack_id=%s minutes=%s price=%s user=%s email=%r",
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
            error_redirect=url_for("minutos.comprar_minutos", pack_slug=pack_slug),
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


@minutos_bp.route("/<pack_slug>/one-click", methods=["GET"])  # type: ignore
def one_click(pack_slug: str):
    """One-Click uprchase for registered users"""
    is_authenticated_user = bool(current_user and getattr(current_user, "is_authenticated", False))
    if not is_authenticated_user:
        abort(403)
    if not current_user.preferred_payment or not current_user.email or not current_user.username:
        abort(403)

    pack = MinutePack.query.filter_by(slug=pack_slug, is_active=True).first_or_404()

    duplicate_cutoff = datetime.now() - timedelta(minutes=2)
    duplicate_filter = and_(
        OrderItem.item_type == OrderItemType.MINUTE_PACK,
        OrderItem.item_id == pack.id,
    )
    duplicate_query = Order.query.filter(
        Order.status == OrderStatus.PENDING,
        Order.provider == current_user.preferred_payment,
        Order.amount == pack.price,
        Order.shipping_email == current_user.email,
        Order.created_at >= duplicate_cutoff,
        Order.items.any(duplicate_filter),
    ).order_by(Order.created_at.desc())
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
            current_user.email,
        )
        order = existing_order
    else:
        order = Order(
            amount=Decimal(str(pack.price)),
            currency=pack.currency,
            provider=current_user.preferred_payment,
            email=current_user.email,
            shipping_phone=current_user.username,
            user=current_user,
            firenze_client_id=current_user.firenze_client_id,
        )
        db.session.add(order)
        db.session.flush()

    item = OrderItem(
        order_id=order.id,
        item_type=OrderItemType.MINUTE_PACK,
        item_id=pack.id,
        name=f"{pack.minutes} minutos de tarot (One-Click)",
        quantity=1,
        unit_price=Decimal(str(pack.price)),
        currency=pack.currency,
    )
    db.session.add(item)
    db.session.commit()

    logger.info(
        "Order created via One-Click: order=%s pack_id=%s minutes=%s price=%s user=%s email=%r",
        order.id,
        pack.id,
        pack.minutes,
        pack.price,
        order.user_id,
        current_user.email,
    )

    return create_payment_and_redirect(
        order,
        current_user.preferred_payment,
        email=current_user.email,
        error_redirect=url_for("minutos.comprar_minutos", pack_slug=pack_slug),
    )
