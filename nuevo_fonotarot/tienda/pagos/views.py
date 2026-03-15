"""Payment callbacks, order status, store index and customer profile."""

from flask import abort, flash, redirect, render_template, request, url_for
from flask_security import current_user

from ...decorators import login_required_modal
from ...extensions import db
from ...log import get_logger
from ...models import MinutePack, Order, OrderStatus, Product, SubscriptionPlan
from ..utils import _get_cart, _save_cart
from . import pagos_bp

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Store index
# ---------------------------------------------------------------------------


@pagos_bp.route("/")
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


# ---------------------------------------------------------------------------
# Customer profile
# ---------------------------------------------------------------------------


@pagos_bp.route("/perfil/", methods=["GET", "POST"])
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
        return redirect(url_for("pagos.perfil"))

    return render_template(
        "tienda/perfil.html",
        user=current_user,
        cart_count=len(_get_cart()),
    )


# ---------------------------------------------------------------------------
# Payment callbacks
# ---------------------------------------------------------------------------


@pagos_bp.route("/pago/confirmacion", methods=["POST"])
def pago_confirmacion():
    """Server-to-server payment confirmation webhook (all providers).

    The providers call this URL after payment is processed.
    We look up the Order directly by ``transaction_id`` and update its
    fulfillment ``status`` based on the payment ``state``.
    """
    token = request.form.get("token") or request.form.get("payment_id") or ""
    if not token:
        logger.warning("pago_confirmacion: webhook received with no token")
        abort(400)

    logger.debug("pago_confirmacion: received webhook token=%r", token)
    try:
        order = Order.query.filter_by(transaction_id=token).first()
        if order and order.status == OrderStatus.PENDING:
            logger.debug("pago_confirmacion: order=%s state=%r", order.id, order.state)
            if order.state == "succeeded":
                order.status = OrderStatus.PAID
                logger.info(
                    "Payment confirmed (succeeded): order=%s token=%r", order.id, token
                )
            elif order.state in ("failed", "cancelled"):
                order.status = OrderStatus.FAILED
                logger.warning(
                    "Payment failed/cancelled: order=%s state=%r token=%r",
                    order.id,
                    order.state,
                    token,
                )
            db.session.commit()
    except Exception as exc:
        logger.error("Payment confirmation error: %s", exc, exc_info=True)
    return "OK", 200


@pagos_bp.route("/pago/retorno/<order_id>")
def pago_retorno(order_id: str):
    """User-facing return page after payment (success or cancel)."""
    order = Order.query.filter_by(merchants_id=order_id).first_or_404()
    logger.debug(
        "pago_retorno: merchants_id=%s status=%r transaction_id=%r",
        order_id,
        order.status,
        order.transaction_id,
    )

    # Sync payment state from provider and update order fulfillment status.
    if order.transaction_id and order.status == OrderStatus.PENDING:
        try:
            order.sync_from_provider()
            logger.debug("pago_retorno: synced order=%s new_state=%r", order_id, order.state)
            if order.state == "succeeded":
                order.status = OrderStatus.PAID
                logger.info("Payment return: order=%s status updated to PAID", order_id)
                db.session.commit()
            elif order.state in ("failed", "cancelled"):
                order.status = OrderStatus.FAILED
                logger.warning(
                    "Payment return: order=%s status updated to FAILED (state=%r)",
                    order_id,
                    order.state,
                )
                db.session.commit()
        except Exception as exc:
            logger.error("Payment return sync error: %s", exc, exc_info=True)

    return redirect(url_for("pagos.orden_estado", order_id=order.id))


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


@pagos_bp.route("/orden/<int:order_id>/")
def orden_estado(order_id: int):
    """Show the status of a specific order."""
    order = Order.query.get_or_404(order_id)
    items = list(order.items)
    return render_template("tienda/orden_estado.html", order=order, items=items)
