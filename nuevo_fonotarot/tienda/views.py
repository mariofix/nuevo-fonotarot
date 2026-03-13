"""Views for the tienda (store) blueprint."""

import logging
from decimal import Decimal

from flask import abort, flash, redirect, render_template, request, session, url_for
from flask_security import current_user

from ..decorators import login_required_modal
from ..models import MinutePack, Order, OrderItem, Product, SubscriptionPlan
from ..extensions import db, merchants_ext
from . import tienda_bp

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CART_SESSION_KEY = "tienda_cart"

# Allowed internal path prefixes for the `next` redirect parameter.
_SAFE_NEXT_PREFIXES = ("/tienda/", "/")


def _safe_next(default: str) -> str:
    """Return a safe internal redirect URL from the POST ``next`` parameter.

    External URLs and absolute URLs with a host are rejected and the
    *default* is returned instead, preventing open-redirect attacks.
    """
    from urllib.parse import urlparse
    raw = request.form.get("next", "").strip()
    if not raw:
        return default
    parsed = urlparse(raw)
    # Reject anything with a scheme or netloc (e.g. "https://evil.com/").
    if parsed.scheme or parsed.netloc:
        return default
    return raw


def _get_cart() -> list:
    """Return the current cart from the session (list of item dicts)."""
    return session.get(CART_SESSION_KEY, [])


def _save_cart(cart: list) -> None:
    session[CART_SESSION_KEY] = cart
    session.modified = True


def _cart_total(cart: list) -> int:
    return sum(item["unit_price"] * item["quantity"] for item in cart)


def _create_payment_and_redirect(order: Order, payment_method: str, email: str) -> object:
    """Create a checkout session via flask-merchants and redirect to the provider.

    Returns a Flask redirect response.
    """
    confirmation_url = url_for("tienda.pago_confirmacion", _external=True)
    success_url = url_for("tienda.pago_retorno", order_id=order.id, _external=True)

    # Build provider-specific confirmation URL into the metadata so the
    # FlowProvider confirmation_url can be forwarded through request metadata.
    logger.debug(
        "Creating checkout session via %s for order=%s amount=%s email=%r",
        payment_method,
        order.id,
        order.total,
        email,
    )
    try:
        client = merchants_ext.get_client(payment_method)
        checkout_session = client.payments.create_checkout(
            amount=Decimal(str(order.total)),
            currency="CLP",
            success_url=success_url,
            cancel_url=url_for("tienda.index", _external=True),
            metadata={
                "order_id": str(order.id),
                "confirmation_url": confirmation_url,
                "email": email,
            },
        )
    except Exception as exc:
        logger.error("Payment creation error (%s): %s", payment_method, exc, exc_info=True)
        flash("Error al conectar con el proveedor de pago. Intenta más tarde.", "danger")
        return redirect(url_for("tienda.checkout"))

    order.payment_token = checkout_session.session_id
    db.session.commit()

    logger.info(
        "Checkout session created: order=%s provider=%s token=%s",
        order.id,
        payment_method,
        checkout_session.session_id,
    )

    merchants_ext.save_session(
        checkout_session,
        request_payload={
            "order_id": order.id,
            "amount": str(order.total),
            "currency": "CLP",
            "provider": payment_method,
        },
    )

    return redirect(checkout_session.redirect_url)


# ---------------------------------------------------------------------------
# Store pages
# ---------------------------------------------------------------------------


@tienda_bp.route("/")
def index():
    """Main store page: featured products across all categories."""
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    subscription_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price).all()
    featured_products = Product.query.filter_by(is_active=True, is_featured=True).limit(6).all()
    cart = _get_cart()
    return render_template(
        "tienda/index.html",
        minute_packs=minute_packs,
        subscription_plans=subscription_plans,
        featured_products=featured_products,
        cart_count=len(cart),
    )


@tienda_bp.route("/minutos/")
def minutos():
    """Prepaid tarot minute packs."""
    packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    cart = _get_cart()
    return render_template("tienda/minutos.html", packs=packs, cart_count=len(cart))


@tienda_bp.route("/suscripciones/")
def suscripciones():
    """Monthly tarot subscription plans."""
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price).all()
    cart = _get_cart()
    return render_template("tienda/suscripciones.html", plans=plans, cart_count=len(cart))


@tienda_bp.route("/productos/")
def productos():
    """Physical esoteric products."""
    category = request.args.get("categoria")
    query = Product.query.filter_by(is_active=True)
    if category:
        query = query.filter_by(category=category)
    items = query.order_by(Product.name).all()
    categories = Product.CATEGORY_CHOICES
    cart = _get_cart()
    return render_template(
        "tienda/productos.html",
        products=items,
        categories=categories,
        active_category=category,
        cart_count=len(cart),
    )


@tienda_bp.route("/productos/<slug>")
def producto_detalle(slug: str):
    """Single product detail page."""
    product = Product.query.filter_by(slug=slug, is_active=True).first()
    if product is None:
        abort(404)
    cart = _get_cart()
    return render_template("tienda/producto_detalle.html", product=product, cart_count=len(cart))


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


@tienda_bp.route("/carrito/")
def carrito():
    """Display the shopping cart."""
    cart = _get_cart()
    total = _cart_total(cart)
    return render_template("tienda/carrito.html", cart=cart, total=total, cart_count=len(cart))


@tienda_bp.route("/carrito/agregar", methods=["POST"])
def agregar_al_carrito():
    """Add an item to the cart.

    Rules:
    - Subscriptions cannot be added to the cart (use the dedicated payment-link flow).
    - Physical products can be added; the profile check is enforced at checkout.
    - Minute packs can be added or purchased directly via fast checkout.
    """
    item_type = request.form.get("item_type")
    item_id = request.form.get("item_id", type=int)
    quantity = request.form.get("quantity", 1, type=int)

    logger.debug("agregar_al_carrito: item_type=%r item_id=%r quantity=%r", item_type, item_id, quantity)

    if item_type == OrderItem.ITEM_TYPE_SUBSCRIPTION:
        logger.warning(
            "Subscription item_id=%r cannot be added to cart; redirecting user to subscription flow",
            item_id,
        )
        flash(
            "Las suscripciones no se pueden agregar al carrito. "
            "Usa el enlace de pago para suscribirte.",
            "warning",
        )
        next_url = _safe_next(url_for("tienda.suscripciones"))
        return redirect(next_url)

    if item_type == OrderItem.ITEM_TYPE_MINUTE_PACK:
        obj = MinutePack.query.get(item_id)
        if obj is None or not obj.is_active:
            abort(404)
        name = f"{obj.minutes} minutos de tarot"
        unit_price = obj.price
    elif item_type == OrderItem.ITEM_TYPE_PRODUCT:
        obj = Product.query.get(item_id)
        if obj is None or not obj.is_active:
            abort(404)
        name = obj.name
        unit_price = obj.price
    else:
        abort(400)

    cart = _get_cart()
    # Merge with existing line if same item_type+item_id
    for line in cart:
        if line["item_type"] == item_type and line["item_id"] == item_id:
            line["quantity"] += quantity
            break
    else:
        cart.append({
            "item_type": item_type,
            "item_id": item_id,
            "name": name,
            "unit_price": unit_price,
            "quantity": quantity,
        })
    _save_cart(cart)
    logger.debug("Cart updated: item_type=%r item_id=%r qty=%r total_lines=%d", item_type, item_id, quantity, len(cart))
    flash("Producto agregado al carrito.", "success")
    next_url = _safe_next(url_for("tienda.carrito"))
    return redirect(next_url)


@tienda_bp.route("/carrito/eliminar", methods=["POST"])
def eliminar_del_carrito():
    """Remove a line from the cart by index."""
    index = request.form.get("index", type=int)
    cart = _get_cart()
    if index is not None and 0 <= index < len(cart):
        cart.pop(index)
        _save_cart(cart)
    return redirect(url_for("tienda.carrito"))


@tienda_bp.route("/carrito/vaciar", methods=["POST"])
def vaciar_carrito():
    """Empty the cart."""
    _save_cart([])
    return redirect(url_for("tienda.carrito"))


# ---------------------------------------------------------------------------
# Fast Checkout – "Buy Now" for minute packs
# ---------------------------------------------------------------------------


@tienda_bp.route("/minutos/<int:pack_id>/comprar", methods=["GET", "POST"])
def comprar_minutos(pack_id: int):
    """Fast checkout for a single minute pack.

    GET  → show the checkout form (payment method + contact details).
    POST → create order + redirect to payment gateway.

    Three customer variants:
    - Anonymous: must supply email and phone on every purchase.
    - Known (authenticated, no physical profile): email pre-filled, no shipping.
    - Physical (authenticated, full profile): all data pre-filled.
    """
    pack = MinutePack.query.filter_by(id=pack_id, is_active=True).first_or_404()

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("comprar_minutos POST: pack_id=%s payment_method=%r", pack_id, payment_method)
        if payment_method not in ("flow", "khipu"):
            logger.warning("Invalid payment method %r for pack_id=%s", payment_method, pack_id)
            flash("Método de pago no válido.", "danger")
            return redirect(url_for("tienda.comprar_minutos", pack_id=pack_id))

        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        if not email:
            logger.debug("comprar_minutos: missing email for pack_id=%s", pack_id)
            flash("El email es obligatorio.", "danger")
            return redirect(url_for("tienda.comprar_minutos", pack_id=pack_id))

        order = Order(
            total=pack.price,
            payment_method=payment_method,
            shipping_email=email,
            shipping_phone=phone,
        )
        if current_user.is_authenticated:
            order.user_id = current_user.id

        db.session.add(order)
        db.session.flush()

        item = OrderItem(
            order_id=order.id,
            item_type=OrderItem.ITEM_TYPE_MINUTE_PACK,
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

        return _create_payment_and_redirect(order, payment_method, email)

    # GET – detect preferred payment method for fast redirect
    preferred = None
    prefilled_email = ""
    prefilled_phone = ""
    if current_user.is_authenticated:
        preferred = current_user.preferred_payment
        prefilled_email = current_user.email or ""
        prefilled_phone = current_user.phone or ""

    return render_template(
        "tienda/comprar_minutos.html",
        pack=pack,
        preferred=preferred,
        prefilled_email=prefilled_email,
        prefilled_phone=prefilled_phone,
        cart_count=len(_get_cart()),
    )


# ---------------------------------------------------------------------------
# Customer profile
# ---------------------------------------------------------------------------


@tienda_bp.route("/perfil/", methods=["GET", "POST"])
@login_required_modal
def perfil():
    """View and update the logged-in customer's profile."""

    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip() or None
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.rut = request.form.get("rut", "").strip() or None
        current_user.address = request.form.get("address", "").strip() or None
        current_user.commune = request.form.get("commune", "").strip() or None
        current_user.postal_code = request.form.get("postal_code", "").strip() or None
        pref = request.form.get("preferred_payment", "").strip()
        current_user.preferred_payment = pref if pref in ("flow", "khipu") else None
        db.session.commit()
        logger.info("Profile updated for user=%s", current_user.id)
        flash("Perfil actualizado correctamente.", "success")
        return redirect(url_for("tienda.perfil"))

    return render_template(
        "tienda/perfil.html",
        user=current_user,
        cart_count=len(_get_cart()),
    )


# ---------------------------------------------------------------------------
# Subscription payment links
# ---------------------------------------------------------------------------


@tienda_bp.route("/suscripciones/<int:plan_id>/link-pago", methods=["GET", "POST"])
@login_required_modal
def suscripcion_link_pago(plan_id: int):
    """Generate a one-off payment link for a subscription renewal.

    Only accessible to authenticated users.
    POST creates an order and surfaces the payment link via flash message
    (in production this would be emailed by the admin/scheduler).
    """

    plan = SubscriptionPlan.query.filter_by(id=plan_id, is_active=True).first_or_404()

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("suscripcion_link_pago POST: plan_id=%s user=%s payment_method=%r", plan_id, current_user.id, payment_method)
        if payment_method not in ("flow", "khipu"):
            logger.warning("Invalid payment method %r for subscription plan_id=%s user=%s", payment_method, plan_id, current_user.id)
            flash("Método de pago no válido.", "danger")
            return redirect(url_for("tienda.suscripcion_link_pago", plan_id=plan_id))

        order = Order(
            user_id=current_user.id,
            total=plan.price,
            payment_method=payment_method,
            shipping_email=current_user.email,
        )
        db.session.add(order)
        db.session.flush()

        item = OrderItem(
            order_id=order.id,
            item_type=OrderItem.ITEM_TYPE_SUBSCRIPTION,
            item_id=plan.id,
            name=f"Suscripción {plan.name}",
            quantity=1,
            unit_price=plan.price,
        )
        db.session.add(item)
        db.session.commit()

        # In production, an email with this URL would be sent by the scheduler.
        payment_url = url_for(
            "tienda.iniciar_pago_suscripcion", order_id=order.id, _external=True
        )
        logger.info(
            "Subscription payment link created: order=%s plan=%s user=%s provider=%s",
            order.id,
            plan.id,
            current_user.id,
            payment_method,
        )
        flash(
            f"Enlace de pago generado. Accede directamente: {payment_url}",
            "success",
        )
        return redirect(url_for("tienda.orden_estado", order_id=order.id))

    return render_template(
        "tienda/suscripcion_link_pago.html",
        plan=plan,
        cart_count=len(_get_cart()),
    )


@tienda_bp.route("/pago/suscripcion/<int:order_id>/iniciar")
def iniciar_pago_suscripcion(order_id: int):
    """Redirect to payment gateway for a subscription payment link."""
    order = Order.query.get_or_404(order_id)
    logger.debug("iniciar_pago_suscripcion: order=%s status=%r", order_id, order.status)
    if order.status != Order.STATUS_PENDING:
        logger.warning(
            "iniciar_pago_suscripcion: order=%s already processed (status=%r), skipping",
            order_id,
            order.status,
        )
        flash("Esta orden ya fue procesada.", "info")
        return redirect(url_for("tienda.orden_estado", order_id=order.id))
    email = order.shipping_email or ""
    logger.info("Initiating subscription payment: order=%s provider=%r email=%r", order_id, order.payment_method, email)
    return _create_payment_and_redirect(order, order.payment_method, email)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@tienda_bp.route("/checkout/", methods=["GET", "POST"])
def checkout():
    """Checkout page: shipping info + payment method selection.

    Physical goods require a logged-in user with a complete physical profile
    (full_name, RUT, address, commune, postal_code). If these are missing the
    user is shown an error and redirected to the profile page.

    Subscriptions cannot be added to the cart (only via the dedicated
    subscription payment-link flow). Mixed carts with minute packs + physical
    goods are allowed for Physical Customers.
    """
    cart = _get_cart()
    if not cart:
        logger.debug("checkout: empty cart, redirecting to store index")
        flash("Tu carrito está vacío.", "warning")
        return redirect(url_for("tienda.index"))

    has_physical = any(i["item_type"] == OrderItem.ITEM_TYPE_PRODUCT for i in cart)
    total = _cart_total(cart)
    logger.debug("checkout: lines=%d has_physical=%s total=%s", len(cart), has_physical, total)

    # Physical goods require a full authenticated profile.
    if has_physical:
        if not current_user.is_authenticated:
            logger.warning("checkout: unauthenticated user attempted to buy physical goods")
            flash(
                "Para comprar productos físicos debes iniciar sesión y completar tu perfil.",
                "warning",
            )
            return redirect(url_for("security.login"))
        if not current_user.has_physical_profile:
            logger.warning(
                "checkout: user=%s missing physical profile for physical goods purchase",
                current_user.id,
            )
            flash(
                "Para comprar productos físicos debes completar tu perfil con "
                "Nombre Completo, RUT, Dirección, Comuna y Código Postal.",
                "danger",
            )
            return redirect(url_for("tienda.perfil"))

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        logger.debug("checkout POST: payment_method=%r user=%s", payment_method, getattr(current_user, "id", None))
        if payment_method not in ("flow", "khipu"):
            logger.warning("checkout: invalid payment method %r", payment_method)
            flash("Método de pago no válido.", "danger")
            return redirect(url_for("tienda.checkout"))

        email = request.form.get("shipping_email", "").strip()
        if current_user.is_authenticated:
            email = email or current_user.email

        if not email:
            logger.debug("checkout: missing contact email")
            flash("El email de contacto es obligatorio.", "danger")
            return redirect(url_for("tienda.checkout"))

        order = Order(
            total=total,
            payment_method=payment_method,
            shipping_email=email,
        )
        if current_user.is_authenticated:
            order.user_id = current_user.id

        if has_physical:
            # Use profile data for authenticated physical customers.
            order.shipping_name = current_user.full_name
            order.shipping_phone = current_user.phone
            order.shipping_address = ", ".join(filter(None, [
                current_user.address,
                current_user.commune,
                current_user.postal_code,
            ]))
            order.anonymous_shipping = True  # always anonymous

        db.session.add(order)
        db.session.flush()

        for line in cart:
            item = OrderItem(
                order_id=order.id,
                item_type=line["item_type"],
                item_id=line["item_id"],
                name=line["name"],
                quantity=line["quantity"],
                unit_price=line["unit_price"],
            )
            db.session.add(item)

        db.session.commit()
        _save_cart([])

        logger.info(
            "Cart checkout order created: order=%s lines=%d total=%s user=%s has_physical=%s provider=%s",
            order.id,
            len(cart),
            total,
            order.user_id,
            has_physical,
            payment_method,
        )

        return _create_payment_and_redirect(order, payment_method, email)

    # Prefill email for authenticated users.
    prefilled_email = current_user.email if current_user.is_authenticated else ""

    return render_template(
        "tienda/checkout.html",
        cart=cart,
        total=total,
        has_physical=has_physical,
        cart_count=len(cart),
        prefilled_email=prefilled_email,
    )


# ---------------------------------------------------------------------------
# Payment callbacks
# ---------------------------------------------------------------------------


@tienda_bp.route("/pago/confirmacion", methods=["POST"])
def pago_confirmacion():
    """Server-to-server payment confirmation webhook (all providers).

    The providers call this URL after payment is processed.
    We update the Order status based on the payment session state.
    """
    token = request.form.get("token") or request.form.get("payment_id") or ""
    if not token:
        logger.warning("pago_confirmacion: webhook received with no token")
        abort(400)

    logger.debug("pago_confirmacion: received webhook token=%r", token)
    try:
        stored = merchants_ext.get_session(token)
        if stored:
            order_id = int((stored.get("metadata") or {}).get("order_id", 0))
            order = Order.query.get(order_id)
            if order and order.status == Order.STATUS_PENDING:
                state = stored.get("state", "")
                logger.debug("pago_confirmacion: order=%s state=%r", order_id, state)
                if state == "succeeded":
                    order.status = Order.STATUS_PAID
                    logger.info("Payment confirmed (succeeded): order=%s token=%r", order_id, token)
                elif state in ("failed", "cancelled"):
                    order.status = Order.STATUS_FAILED
                    logger.warning("Payment failed/cancelled: order=%s state=%r token=%r", order_id, state, token)
                db.session.commit()
    except Exception as exc:
        logger.error("Payment confirmation error: %s", exc, exc_info=True)
    return "OK", 200


@tienda_bp.route("/pago/retorno/<int:order_id>")
def pago_retorno(order_id: int):
    """User-facing return page after payment (success or cancel)."""
    order = Order.query.get_or_404(order_id)
    logger.debug("pago_retorno: order=%s status=%r token=%r", order_id, order.status, order.payment_token)

    # Try to sync payment state from provider.
    if order.payment_token and order.status == Order.STATUS_PENDING:
        try:
            stored = merchants_ext.get_session(order.payment_token)
            if stored:
                state = stored.get("state", "")
                logger.debug("pago_retorno: syncing order=%s state=%r", order_id, state)
                if state == "succeeded":
                    order.status = Order.STATUS_PAID
                    logger.info("Payment return: order=%s status updated to PAID", order_id)
                    db.session.commit()
                elif state in ("failed", "cancelled"):
                    order.status = Order.STATUS_FAILED
                    logger.warning("Payment return: order=%s status updated to FAILED (state=%r)", order_id, state)
                    db.session.commit()
        except Exception as exc:
            logger.error("Payment return sync error: %s", exc, exc_info=True)

    return redirect(url_for("tienda.orden_estado", order_id=order.id))


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


@tienda_bp.route("/orden/<int:order_id>/")
def orden_estado(order_id: int):
    """Show the status of a specific order."""
    order = Order.query.get_or_404(order_id)
    items = list(order.items)
    return render_template("tienda/orden_estado.html", order=order, items=items)


