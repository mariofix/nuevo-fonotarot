"""Digital gift-card store and redemption views."""

from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for, abort, current_app, jsonify
from flask_babel import _
from flask_security import current_user

from ...extensions import db
from ...log import get_logger
from ...models import GiftCard, GiftCardProduct, Order, OrderItem, OrderItemType, OrderStatus
from ..utils import _get_cart, create_payment_and_redirect
from . import tarjetas_bp
from .service import normalize_input_code, redeem_gift_card, create_giftcard_pdf

logger = get_logger(__name__)


@tarjetas_bp.route("/")
def index():
    """Public listing for active digital gift-card products."""
    cards = GiftCardProduct.query.filter_by(is_active=True).order_by(GiftCardProduct.price).all()
    return render_template("tienda/tarjetas.html", cards=cards, cart_count=len(_get_cart()))


@tarjetas_bp.route("/canjear", methods=["GET", "POST"])
def canjear():
    """Redeem a purchased gift-card code into user minutes."""
    if not (current_user and current_user.is_authenticated):
        flash(_("Debes iniciar sesión para canjear una tarjeta."), "warning")
        return redirect(url_for("security.login", next=request.url))

    if request.method == "POST":
        raw_code = request.form.get("code", "")
        code = normalize_input_code(raw_code)
        if not code:
            flash(_("Ingresa un código válido."), "danger")
            return redirect(url_for("tarjetas.canjear"))

        gift_card = GiftCard.query.filter_by(code=code).first()
        if gift_card is None:
            flash(_("El código ingresado no existe."), "danger")
            return redirect(url_for("tarjetas.canjear"))

        if gift_card.order_id is not None:
            purchase_order = db.session.get(Order, gift_card.order_id)
            if purchase_order is None or purchase_order.payment_status != "succeeded":
                flash(_("Esta tarjeta todavía no está disponible para canje."), "warning")
                return redirect(url_for("tarjetas.canjear"))

        ok, message = redeem_gift_card(gift_card=gift_card, user=current_user)
        flash(_(message), "success" if ok else "danger")
        return redirect(url_for("tarjetas.canjear"))

    recent_redeemed = (
        GiftCard.query.filter_by(redeemed_by_user_id=current_user.id, status="redeemed")
        .order_by(GiftCard.redeemed_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "tienda/canjear_tarjeta.html",
        recent_redeemed=recent_redeemed,
        cart_count=len(_get_cart()),
    )


@tarjetas_bp.route("/<slug>")
def detalle(slug: str):
    """Gift-card product detail page."""
    card = GiftCardProduct.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template("tienda/tarjeta_detalle.html", card=card, cart_count=len(_get_cart()))


@tarjetas_bp.route("/instrucciones/<data_str>", methods=["GET", "POST"])
def instrucciones(data_str: str):
    """Gift-card product detail page."""
    if not data_str:
        logger.warning("tarjetas.instrucciones: data_str not present")
        return abort(404)
    from cryptography.fernet import Fernet, InvalidToken
    from json import loads as json_loads

    f = Fernet(current_app.config["SECRET_KEY"])
    data = None
    try:
        data = json_loads(f.decrypt(data_str.encode()))
        logger.info(f"{data=}")
    except InvalidToken as e:
        logger.warning(f"InvalidToken: {e}")
    except TypeError:
        logger.warning(f"TypeError: {data_str} no es una cadena de texto")

    if not data:
        return abort(404)

    if not all(k in ["giftcard_id", "order_id", "item_id"] for k in data.keys()):
        logger.warning(f"tarjetas.instrucciones: {data=} malformado")
        return abort(404)

    from ...models import Order, OrderItem, GiftCard
    from ...extensions import db

    order = db.session.get(Order, data.get("order_id"))
    order_item = db.session.get(OrderItem, data.get("item_id"))
    card = db.session.get(GiftCardProduct, order_item.item_id)
    giftcard = GiftCard.query.filter_by(
        id=data.get("giftcard_id"),
        order_id=order.id,
        gift_card_product_id=card.id,
    ).first_or_404()
    pdf_info = {
        "file_name": f"gc-{order.merchants_id.lower()}.pdf",
        "giftcard": giftcard,
        "card": card,
    }

    base_url = current_app.config.get("TRUSTED_HOSTS", ["localhost"])[0]
    site_domain = "https://fonotarot.com"
    card_html = create_giftcard_pdf(pdf_data=pdf_info, base_url=base_url, site_domain=site_domain)
    card_template = render_template(
        "tienda/email/email-giftcard.html", hidecss=True, base_url=site_domain, raw_data=pdf_info, **pdf_info
    )
    if request.method == "POST":

        card_template = render_template(
            "tienda/email/email-giftcard.html", base_url=site_domain, raw_data=pdf_info, **pdf_info
        )
        return jsonify("yeah")

    return render_template(
        "tienda/tarjeta_instrucciones.html",
        card=card,
        order=order,
        item=order_item,
        gc_info=pdf_info,
        card_template=card_template,
    )


@tarjetas_bp.route("/<slug>/comprar", methods=["GET", "POST"])
def comprar(slug: str):
    """Fast checkout for one gift-card product."""
    card = GiftCardProduct.query.filter_by(slug=slug, is_active=True).first_or_404()
    is_authenticated_user = bool(current_user and getattr(current_user, "is_authenticated", False))

    if request.method == "POST":
        payment_method = request.form.get("payment_method", "").strip()
        purchaser_email = request.form.get("email", "").strip().lower()
        recipient_email = request.form.get("recipient_email", "").strip().lower()
        gift_message = request.form.get("gift_message", "").strip()
        quantity_raw = request.form.get("quantity", "1").strip()

        if payment_method not in ("flow", "khipu"):
            flash(_("Método de pago no válido."), "danger")
            return redirect(url_for("tarjetas.comprar", slug=slug))
        if not purchaser_email:
            flash(_("El email del comprador es obligatorio."), "danger")
            return redirect(url_for("tarjetas.comprar", slug=slug))

        quantity = 1

        total_amount = Decimal(str(card.price)) * quantity
        order = Order(
            amount=total_amount,
            currency=card.currency,
            provider=payment_method,
            email=purchaser_email,
            shipping_email=purchaser_email,
            status=OrderStatus.PENDING,
        )
        if is_authenticated_user:
            order.user_id = current_user.id
            order.firenze_client_id = current_user.firenze_client_id

        db.session.add(order)
        db.session.flush()

        item = OrderItem(
            order_id=order.id,
            item_type=OrderItemType.GIFT_CARD,
            item_id=card.id,
            name=card.name,
            quantity=quantity,
            unit_price=Decimal(str(card.price)),
            currency=card.currency,
            fulfillment_data={
                "gift_card_recipient_email": recipient_email or None,
                "gift_card_message": gift_message or None,
            },
        )
        db.session.add(item)
        db.session.commit()

        logger.info(
            "gift_card checkout: created order=%s card=%s qty=%s email=%r recipient=%r",
            order.id,
            card.id,
            quantity,
            purchaser_email,
            recipient_email or None,
        )
        return create_payment_and_redirect(
            order,
            payment_method,
            purchaser_email,
            error_redirect=url_for("tarjetas.comprar", slug=slug),
        )

    prefilled_email = current_user.email if is_authenticated_user else ""
    preferred = current_user.preferred_payment if is_authenticated_user else None
    return render_template(
        "tienda/comprar_tarjeta.html",
        card=card,
        preferred=preferred,
        prefilled_email=prefilled_email,
        cart_count=len(_get_cart()),
    )
