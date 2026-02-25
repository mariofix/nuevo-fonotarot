"""Views for the tienda (store) blueprint."""

import json

from flask import abort, flash, redirect, render_template, request, session, url_for

from ..models import MinutePack, Order, OrderItem, Product, SubscriptionPlan
from ..extensions import db
from . import tienda_bp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CART_SESSION_KEY = "tienda_cart"


def _get_cart() -> list:
    """Return the current cart from the session (list of item dicts)."""
    return session.get(CART_SESSION_KEY, [])


def _save_cart(cart: list) -> None:
    session[CART_SESSION_KEY] = cart
    session.modified = True


def _cart_total(cart: list) -> int:
    return sum(item["unit_price"] * item["quantity"] for item in cart)


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
    """Add an item to the cart."""
    item_type = request.form.get("item_type")
    item_id = request.form.get("item_id", type=int)
    quantity = request.form.get("quantity", 1, type=int)

    if item_type == OrderItem.ITEM_TYPE_MINUTE_PACK:
        obj = MinutePack.query.get(item_id)
        if obj is None or not obj.is_active:
            abort(404)
        name = f"{obj.minutes} minutos de tarot"
        unit_price = obj.price
    elif item_type == OrderItem.ITEM_TYPE_SUBSCRIPTION:
        obj = SubscriptionPlan.query.get(item_id)
        if obj is None or not obj.is_active:
            abort(404)
        name = f"Suscripción {obj.name}"
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
    flash("Producto agregado al carrito.", "success")
    next_url = request.form.get("next") or url_for("tienda.carrito")
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
# Checkout
# ---------------------------------------------------------------------------


@tienda_bp.route("/checkout/", methods=["GET", "POST"])
def checkout():
    """Checkout page: shipping info + payment method selection."""
    cart = _get_cart()
    if not cart:
        flash("Tu carrito está vacío.", "warning")
        return redirect(url_for("tienda.index"))

    has_physical = any(i["item_type"] == OrderItem.ITEM_TYPE_PRODUCT for i in cart)
    total = _cart_total(cart)

    if request.method == "POST":
        payment_method = request.form.get("payment_method")
        if payment_method not in ("flow", "khipu"):
            flash("Método de pago no válido.", "danger")
            return redirect(url_for("tienda.checkout"))

        # Build order
        order = Order(
            total=total,
            payment_method=payment_method,
        )
        if has_physical:
            order.shipping_name = request.form.get("shipping_name", "").strip()
            order.shipping_email = request.form.get("shipping_email", "").strip()
            order.shipping_phone = request.form.get("shipping_phone", "").strip()
            order.anonymous_shipping = True  # always anonymous
            uses_pickup = request.form.get("uses_pickup") == "1"
            order.shipping_uses_pickup = uses_pickup
            if uses_pickup:
                order.shipping_pickup_point = request.form.get("pickup_point", "").strip()
            else:
                order.shipping_address = request.form.get("shipping_address", "").strip()

        db.session.add(order)
        db.session.flush()  # get order.id

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

        # Redirect to payment gateway
        return redirect(url_for("tienda.iniciar_pago", order_id=order.id))

    return render_template(
        "tienda/checkout.html",
        cart=cart,
        total=total,
        has_physical=has_physical,
        cart_count=len(cart),
    )


# ---------------------------------------------------------------------------
# Payment gateways
# ---------------------------------------------------------------------------


@tienda_bp.route("/pago/<int:order_id>/iniciar")
def iniciar_pago(order_id: int):
    """Redirect the customer to the selected payment gateway."""
    order = Order.query.get_or_404(order_id)
    if order.status != Order.STATUS_PENDING:
        flash("Esta orden ya fue procesada.", "info")
        return redirect(url_for("tienda.orden_estado", order_id=order.id))

    from flask import current_app

    if order.payment_method == "flow":
        try:
            from pyflowcl import FlowAPI
            from pyflowcl.Clients import ApiClient

            api_key = current_app.config.get("FLOW_API_KEY", "")
            secret_key = current_app.config.get("FLOW_SECRET_KEY", "")
            api_url = current_app.config.get("FLOW_API_URL", "https://sandbox.flow.cl/api")

            client = ApiClient(api_url, api_key, secret_key)
            api = FlowAPI(client)

            payment_data = {
                "commerceOrder": str(order.id),
                "subject": "Fonotarot - Compra",
                "currency": "CLP",
                "amount": order.total,
                "email": order.shipping_email or "",
                "urlConfirmation": url_for("tienda.flow_confirmacion", _external=True),
                "urlReturn": url_for("tienda.flow_retorno", _external=True),
            }
            result = api.payment.create(payment_data)
            order.payment_token = result.get("token")
            db.session.commit()
            redirect_url = f"{result.get('url')}?token={result.get('token')}"
            return redirect(redirect_url)
        except Exception as exc:
            current_app.logger.error("Flow payment error: %s", exc)
            flash("Error al conectar con Flow. Intenta más tarde.", "danger")
            return redirect(url_for("tienda.checkout"))

    elif order.payment_method == "khipu":
        try:
            import khipu_tools

            khipu_tools.api_key = current_app.config.get("KHIPU_API_KEY", "")
            payment = khipu_tools.Payment.create(
                amount=order.total,
                currency="CLP",
                subject="Fonotarot - Compra",
                transaction_id=str(order.id),
                return_url=url_for("tienda.khipu_retorno", _external=True),
                notify_url=url_for("tienda.khipu_notificacion", _external=True),
            )
            order.payment_token = payment.payment_id
            db.session.commit()
            return redirect(payment.payment_url)
        except Exception as exc:
            current_app.logger.error("Khipu payment error: %s", exc)
            flash("Error al conectar con Khipu. Intenta más tarde.", "danger")
            return redirect(url_for("tienda.checkout"))

    abort(400)


@tienda_bp.route("/pago/flow/confirmacion", methods=["POST"])
def flow_confirmacion():
    """Flow server-to-server payment confirmation callback."""
    token = request.form.get("token")
    if not token:
        abort(400)
    from flask import current_app
    try:
        from pyflowcl import FlowAPI
        from pyflowcl.Clients import ApiClient

        api_key = current_app.config.get("FLOW_API_KEY", "")
        secret_key = current_app.config.get("FLOW_SECRET_KEY", "")
        api_url = current_app.config.get("FLOW_API_URL", "https://sandbox.flow.cl/api")

        client = ApiClient(api_url, api_key, secret_key)
        api = FlowAPI(client)
        result = api.payment.getStatusByToken({"token": token})

        if result.get("status") == 2:  # PAID
            order_id = int(result.get("commerceOrder", 0))
            order = Order.query.get(order_id)
            if order and order.status == Order.STATUS_PENDING:
                order.status = Order.STATUS_PAID
                db.session.commit()
    except Exception as exc:
        current_app.logger.error("Flow confirmation error: %s", exc)
    return "OK", 200


@tienda_bp.route("/pago/flow/retorno")
def flow_retorno():
    """Flow user-redirect return page after payment."""
    token = request.args.get("token")
    if token:
        from flask import current_app
        try:
            from pyflowcl import FlowAPI
            from pyflowcl.Clients import ApiClient

            api_key = current_app.config.get("FLOW_API_KEY", "")
            secret_key = current_app.config.get("FLOW_SECRET_KEY", "")
            api_url = current_app.config.get("FLOW_API_URL", "https://sandbox.flow.cl/api")

            client = ApiClient(api_url, api_key, secret_key)
            api = FlowAPI(client)
            result = api.payment.getStatusByToken({"token": token})
            order_id = int(result.get("commerceOrder", 0))
            order = Order.query.get(order_id)
            if order and result.get("status") == 2 and order.status == Order.STATUS_PENDING:
                order.status = Order.STATUS_PAID
                db.session.commit()
            if order:
                return redirect(url_for("tienda.orden_estado", order_id=order.id))
        except Exception as exc:
            current_app.logger.error("Flow return error: %s", exc)
    flash("No se pudo confirmar el estado del pago.", "warning")
    return redirect(url_for("tienda.index"))


@tienda_bp.route("/pago/khipu/retorno")
def khipu_retorno():
    """Khipu user-redirect return page after payment."""
    payment_id = request.args.get("payment_id") or request.args.get("payment_method")
    order = Order.query.filter_by(payment_token=payment_id).first()
    if order:
        return redirect(url_for("tienda.orden_estado", order_id=order.id))
    return redirect(url_for("tienda.index"))


@tienda_bp.route("/pago/khipu/notificacion", methods=["POST"])
def khipu_notificacion():
    """Khipu server-to-server payment notification webhook."""
    from flask import current_app
    try:
        import khipu_tools

        khipu_tools.api_key = current_app.config.get("KHIPU_API_KEY", "")
        payment_id = request.form.get("payment_id")
        if payment_id:
            payment = khipu_tools.Payment.retrieve(payment_id)
            if payment.status == "done":
                order = Order.query.filter_by(payment_token=payment_id).first()
                if order and order.status == Order.STATUS_PENDING:
                    order.status = Order.STATUS_PAID
                    db.session.commit()
    except Exception as exc:
        current_app.logger.error("Khipu notification error: %s", exc)
    return "OK", 200


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


@tienda_bp.route("/orden/<int:order_id>/")
def orden_estado(order_id: int):
    """Show the status of a specific order."""
    order = Order.query.get_or_404(order_id)
    items = list(order.items)
    return render_template("tienda/orden_estado.html", order=order, items=items)

