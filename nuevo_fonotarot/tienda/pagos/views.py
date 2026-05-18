"""Payment callbacks, order status, and store index."""

from flask import abort, current_app, redirect, render_template, request, url_for

from ...extensions import db
from ...log import get_logger
from ...models import MinutePack, Order, OrderStatus, Product, SubscriptionPlan
from ..utils import _get_cart
from . import pagos_bp

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Firenze client-ID sync
# ---------------------------------------------------------------------------


def _sync_firenze_on_payment(order: Order) -> bool:
    """After payment confirmation, ensure the order (and linked user) have a Firenze client_id.

    If ``order.firenze_client_id`` is already set this is a no-op and returns
    ``True``.  Otherwise a new client is created in Firenze using the order's
    contact details.  For orders tied to a registered user that has no
    ``firenze_client_id`` the value is propagated to the user record as well.

    All errors are swallowed and logged — this must never block payment processing.

    Returns:
        ``True`` if Firenze already had a ``client_id`` or the call succeeded,
        ``False`` if the Firenze call returned no ``client_id`` or failed.
    """
    from ...firenze import create_client as _firenze_create

    if order.firenze_client_id:
        logger.debug(
            "_sync_firenze_on_payment: order=%s already has firenze_client_id=%s",
            order.id,
            order.firenze_client_id,
        )
        return True

    try:
        firenze_phone = (
            (order.user.username or "").strip()
            if order.user and order.user.username
            else (order.shipping_phone or "").strip()
        )
        logger.debug(
            "_sync_firenze_on_payment: creating Firenze client for order=%s (email=%r phone=%r)",
            order.id,
            order.shipping_email,
            firenze_phone,
        )
        client_id = _firenze_create(
            name=order.shipping_name,
            email=order.shipping_email,
            ani=firenze_phone or None,
            transaction_id=order.transaction_id,
        )
        if client_id is not None:
            order.firenze_client_id = client_id
            logger.info(
                "_sync_firenze_on_payment: created Firenze client_id=%s for order=%s",
                client_id,
                order.id,
            )
            
            if order.user_id:
                from ...models import User as _User

                linked_user = db.session.get(_User, order.user_id)
                if linked_user and not linked_user.firenze_client_id:
                    linked_user.firenze_client_id = client_id
                    logger.debug(
                        "_sync_firenze_on_payment: assigned firenze_client_id=%s to user=%s",
                        client_id,
                        linked_user.id,
                    )
            return True
        logger.warning(
            "_sync_firenze_on_payment: no client_id returned for order=%s", order.id
        )
        return False
    except Exception:
        logger.exception(
            "_sync_firenze_on_payment: failed to create Firenze client for order=%s", order.id
        )
        return False


def _send_firenze_failure_email(order: Order) -> None:
    """Notify admin users that Firenze registration failed for a confirmed payment.

    The order payment was confirmed but the Firenze ``create_client`` call did
    not return a ``client_id``.  Admins are asked to use the admin panel action
    "Completar Orden" to retry manually.
    """
    from daleks.contrib.client import DaleksClient

    from ...models import Role

    logger.info("_send_firenze_failure_email: notifying admins about Firenze failure for order=%s", order.id)

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning("_send_firenze_failure_email: DALEKS_URL not configured — skipping email for order=%s", order.id)
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        logger.debug("_send_firenze_failure_email: no admin role found in database")
        return
    admin_emails = [u.email for u in admin_role.users.all() if u.active and u.email]
    if not admin_emails:
        logger.debug("_send_firenze_failure_email: no active admin users with email found")
        return

    logger.debug("_send_firenze_failure_email: sending to %d admin(s) for order=%s", len(admin_emails), order.id)
    try:
        html_body = render_template(
            "tienda/email/firenze_fallo.html",
            order=order,
            site_url=site_url,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            for email in admin_emails:
                client.send_email(
                    from_address=from_address,
                    to=[email],
                    subject=f"[Admin] Fallo Firenze — Orden #{order.id} pago confirmado",
                    html_body=html_body,
                )
        logger.info("_send_firenze_failure_email: notification sent to admins for order=%s", order.id)
    except Exception:
        logger.exception(
            "_send_firenze_failure_email: failed to send notification for order=%s", order.id
        )


def _send_order_confirmation_email(order: Order) -> None:
    """Send order confirmation email to customer and admin users via Daleks."""
    from daleks.contrib.client import DaleksClient

    from ...models import Role

    logger.info("_send_order_confirmation_email: sending confirmation emails for order=%s", order.id)

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning("_send_order_confirmation_email: DALEKS_URL not configured — skipping for order=%s", order.id)
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

    recipient_name = order.shipping_name or order.shipping_email or ""

    # --- Customer email ---
    if order.shipping_email:
        try:
            logger.debug(
                "_send_order_confirmation_email: sending customer confirmation to %s for order=%s",
                order.shipping_email,
                order.id,
            )
            html_body = render_template(
                "tienda/email/orden_confirmada.html",
                order=order,
                recipient_name=recipient_name,
                site_url=site_url,
            )
            with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
                client.send_email(
                    from_address=from_address,
                    to=[order.shipping_email],
                    subject=f"Orden #{order.id} confirmada — Fonotarot",
                    html_body=html_body,
                )
            logger.info("Order confirmation email sent to customer %s for order=%s", order.shipping_email, order.id)
        except Exception:
            logger.exception("Failed to send order confirmation email to %s for order=%s", order.shipping_email, order.id)

    # --- Admin notification ---
    logger.debug("_send_order_confirmation_email: looking up admin role for order=%s", order.id)
    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role:
        admin_emails = [u.email for u in admin_role.users.all() if u.active and u.email]
        if admin_emails:
            logger.debug(
                "_send_order_confirmation_email: sending admin notification to %d admin(s) for order=%s",
                len(admin_emails),
                order.id,
            )
            try:
                html_body = render_template(
                    "tienda/email/orden_confirmada.html",
                    order=order,
                    recipient_name=f"Admin (compra de {recipient_name})",
                    site_url=site_url,
                )
                with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
                    for email in admin_emails:
                        client.send_email(
                            from_address=from_address,
                            to=[email],
                            subject=f"[Admin] Nueva orden #{order.id} pagada — ${order.total_display}",
                            html_body=html_body,
                        )
                logger.info("Admin notification sent for order=%s (sent to %d admin(s))", order.id, len(admin_emails))
            except Exception:
                logger.exception("Failed to send admin notification for order=%s", order.id)
        else:
            logger.debug("_send_order_confirmation_email: no active admin users with email for order=%s", order.id)
    else:
        logger.debug("_send_order_confirmation_email: no admin role found in database for order=%s", order.id)


def _complete_succeeded_order(order: Order, label: str) -> None:
    """Shared post-payment completion logic for a ``succeeded`` order.

    Calls Firenze to register the client.  If Firenze succeeds, the order is
    marked PAID and confirmation emails are sent to the customer and admins.
    If Firenze fails, the order remains PENDING and an admin failure email is
    sent so operators can retry via the "Completar Orden" admin action.

    Args:
        order: The Order to complete (must have ``state == "succeeded"``).
        label: Short context string used in log messages (e.g. ``"webhook"``).
    """
    logger.info("_complete_succeeded_order: processing succeeded order=%s from %s", order.id, label)
    
    firenze_ok = _sync_firenze_on_payment(order)
    if firenze_ok:
        order.status = OrderStatus.PAID
        logger.info(
            "_complete_succeeded_order: order=%s marked PAID (firenze_client_id=%s)",
            order.id,
            order.firenze_client_id,
        )
        db.session.commit()
        _send_order_confirmation_email(order)
    else:
        logger.warning(
            "_complete_succeeded_order: Firenze sync failed for order=%s — order remains PENDING, notifying admins",
            order.id,
        )
        db.session.commit()
        _send_firenze_failure_email(order)


def _find_order_by_payment_id(payment_id: str) -> Order | None:
    """Return the order linked to a provider payment identifier."""
    return Order.query.filter_by(transaction_id=payment_id).first()


def _apply_payment_state_to_order(order: Order, *, payment_id: str, provider: str | None, state: str | None, label: str) -> None:
    """Apply a webhook-derived payment state to an order."""
    if order.status != OrderStatus.PENDING:
        logger.debug(
            "_apply_payment_state_to_order: order=%s already handled with status=%s (payment_id=%r provider=%r state=%r)",
            order.id,
            order.status,
            payment_id,
            provider,
            state,
        )
        return

    if state == "succeeded":
        _complete_succeeded_order(order, label)
        return

    if state in {"failed", "cancelled"}:
        order.status = OrderStatus.FAILED
        db.session.commit()
        logger.warning(
            "_apply_payment_state_to_order: order=%s marked FAILED from payment_id=%r provider=%r state=%r",
            order.id,
            payment_id,
            provider,
            state,
        )
        return

    logger.debug(
        "_apply_payment_state_to_order: ignoring non-final event for order=%s payment_id=%r provider=%r state=%r",
        order.id,
        payment_id,
        provider,
        state,
    )


def _handle_khipu_webhook_event(event) -> None:
    """Handle Khipu webhook events emitted by flask-merchants."""
    payment_id = getattr(event, "payment_id", None)
    state = getattr(getattr(event, "state", None), "value", None)
    provider = getattr(event, "provider", None)

    if not payment_id:
        logger.warning(
            "_handle_khipu_webhook_event: missing payment_id for provider=%r event_type=%r",
            provider,
            getattr(event, "event_type", None),
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            "_handle_khipu_webhook_event: no order found for payment_id=%r provider=%r state=%r",
            payment_id,
            provider,
            state,
        )
        return

    _apply_payment_state_to_order(
        order,
        payment_id=payment_id,
        provider=provider,
        state=state,
        label="webhook-khipu",
    )


def _handle_flow_webhook_event(event) -> None:
    """Handle Flow webhook events emitted by flask-merchants."""
    payment_id = getattr(event, "payment_id", None)
    provider = getattr(event, "provider", None)

    if not payment_id:
        logger.warning(
            "_handle_flow_webhook_event: missing payment_id for provider=%r event_type=%r",
            provider,
            getattr(event, "event_type", None),
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            "_handle_flow_webhook_event: no order found for payment_id=%r provider=%r",
            payment_id,
            provider,
        )
        return

    if order.status != OrderStatus.PENDING:
        logger.debug(
            "_handle_flow_webhook_event: order=%s already handled with status=%s (payment_id=%r)",
            order.id,
            order.status,
            payment_id,
        )
        return

    try:
        order.sync_from_provider()
    except Exception:
        logger.exception(
            "_handle_flow_webhook_event: failed to sync order=%s from provider payment_id=%r",
            order.id,
            payment_id,
        )
        return

    _apply_payment_state_to_order(
        order,
        payment_id=payment_id,
        provider=provider,
        state=order.state,
        label="webhook-flow",
    )


def _handle_stripe_webhook_event(event) -> None:
    """Handle Stripe webhook events emitted by flask-merchants."""
    payment_id = getattr(event, "payment_id", None)
    state = getattr(getattr(event, "state", None), "value", None)
    provider = getattr(event, "provider", None)

    if not payment_id:
        logger.warning(
            "_handle_stripe_webhook_event: missing payment_id for provider=%r event_type=%r",
            provider,
            getattr(event, "event_type", None),
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            "_handle_stripe_webhook_event: no order found for payment_id=%r provider=%r state=%r",
            payment_id,
            provider,
            state,
        )
        return

    _apply_payment_state_to_order(
        order,
        payment_id=payment_id,
        provider=provider,
        state=state,
        label="webhook-stripe",
    )


def _handle_payment_webhook_event(event) -> None:
    """Dispatch payment webhook events by provider."""
    provider = getattr(event, "provider", None)

    if provider == "khipu":
        _handle_khipu_webhook_event(event)
        return
    if provider == "flow":
        _handle_flow_webhook_event(event)
        return
    if provider == "stripe":
        _handle_stripe_webhook_event(event)
        return

    logger.debug(
        "_handle_payment_webhook_event: unsupported provider=%r event_type=%r payment_id=%r",
        provider,
        getattr(event, "event_type", None),
        getattr(event, "payment_id", None),
    )


def _handle_payment_webhook_finished(*, event, **kwargs) -> None:
    """Signal receiver that runs after flask-merchants finishes webhook dispatch."""
    _handle_payment_webhook_event(event)


# ---------------------------------------------------------------------------
# Store index
# ---------------------------------------------------------------------------


@pagos_bp.route("/")
def index():
    """Main store page: featured products across all categories."""
    logger.debug("pagos.index: loading store page")
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    subscription_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price).all()
    featured_products = Product.query.filter_by(is_active=True, is_featured=True).limit(6).all()
    cart = _get_cart()
    logger.debug(
        "pagos.index: loaded %d minute packs, %d subscription plans, %d featured products, cart_count=%d",
        len(minute_packs),
        len(subscription_plans),
        len(featured_products),
        len(cart),
    )
    return render_template(
        "tienda/index.html",
        minute_packs=minute_packs,
        subscription_plans=subscription_plans,
        featured_products=featured_products,
        cart_count=len(cart),
    )


# ---------------------------------------------------------------------------
# Payment callbacks
# ---------------------------------------------------------------------------

# TO BE DEPRECATED; DO NOT DELETE
# @pagos_bp.route("/pago/confirmacion", methods=["POST"])
# def pago_confirmacion():
#     """Server-to-server payment confirmation webhook (all providers).

#     The providers call this URL after payment is processed.
#     We look up the Order directly by ``transaction_id`` and update its
#     fulfillment ``status`` based on the payment ``state``.
#     """
#     token = request.form.get("token") or request.form.get("payment_id") or ""
#     if not token:
#         logger.warning("pago_confirmacion: webhook received with no token — rejecting")
#         abort(400)

#     logger.info("pago_confirmacion: webhook received with token=%r", token)
#     try:
#         order = Order.query.filter_by(transaction_id=token).first()
#         if order:
#             logger.debug(
#                 "pago_confirmacion: found order=%s with status=%s",
#                 order.id,
#                 order.status,
#             )
#             if order.status == OrderStatus.PENDING:
#                 logger.debug("pago_confirmacion: order=%s is PENDING, syncing from provider", order.id)
#                 try:
#                     order.sync_from_provider()
#                     logger.info(
#                         "pago_confirmacion: synced order=%s new_state=%r", order.id, order.state
#                     )
#                 except Exception as sync_exc:
#                     logger.warning(
#                         "pago_confirmacion: sync_from_provider failed for order=%s — %s",
#                         order.id,
#                         sync_exc,
#                     )
#                 if order.state == "succeeded":
#                     _complete_succeeded_order(order, "webhook")
#                 elif order.state in ("failed", "cancelled"):
#                     order.status = OrderStatus.FAILED
#                     logger.warning(
#                         "pago_confirmacion: payment failed/cancelled — order=%s state=%r token=%r",
#                         order.id,
#                         order.state,
#                         token,
#                     )
#                     db.session.commit()
#             else:
#                 logger.debug(
#                     "pago_confirmacion: order=%s not in PENDING status (current=%s), skipping sync",
#                     order.id,
#                     order.status,
#                 )
#         else:
#             logger.warning("pago_confirmacion: no order found for token=%r", token)
#     except Exception as exc:
#         logger.error("pago_confirmacion: error processing webhook — %s", exc, exc_info=True)
#     return "OK", 200


@pagos_bp.route("/pago/retorno/<order_id>")
def pago_retorno(order_id: str):
    """User-facing return page after payment (success or cancel)."""
    order = Order.query.filter_by(merchants_id=order_id).first_or_404()
    logger.info(
        "pago_retorno: user returned from payment (merchants_id=%s order=%s status=%s)",
        order_id,
        order.id,
        order.status,
    )
    logger.debug(
        "pago_retorno: order details — transaction_id=%r state=%r",
        order.transaction_id,
        order.state,
    )

    # Sync payment state from provider and update order fulfillment status.
    if order.transaction_id and order.status == OrderStatus.PENDING:
        logger.debug("pago_retorno: order=%s is PENDING, syncing from provider", order.id)
        try:
            order.sync_from_provider()
            logger.info("pago_retorno: synced order=%s new_state=%r", order.id, order.state)
            if order.state == "succeeded":
                _complete_succeeded_order(order, "retorno")
            elif order.state in ("failed", "cancelled"):
                order.status = OrderStatus.FAILED
                logger.warning(
                    "pago_retorno: payment failed/cancelled — order=%s status updated to FAILED (state=%r)",
                    order.id,
                    order.state,
                )
                db.session.commit()
        except Exception as exc:
            logger.error("pago_retorno: sync error for order=%s — %s", order.id, exc, exc_info=True)
    else:
        logger.debug(
            "pago_retorno: order=%s not syncing (has_transaction_id=%s status=%s)",
            order.id,
            bool(order.transaction_id),
            order.status,
        )

    return redirect(url_for("pagos.orden_estado", order_id=order.id))


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


@pagos_bp.route("/orden/<int:order_id>/")
def orden_estado(order_id: int):
    """Show the status of a specific order."""
    logger.debug("pagos.orden_estado: user checking order=%s status", order_id)
    order = Order.query.get_or_404(order_id)
    items = list(order.items)
    logger.debug(
        "pagos.orden_estado: order=%s status=%s has %d item(s)",
        order_id,
        order.status,
        len(items),
    )
    return render_template("tienda/orden_estado.html", order=order, items=items)
