"""Payment callbacks, order status, and store index."""

import random
import re

from flask import current_app, redirect, render_template, url_for
from sqlalchemy.exc import SQLAlchemyError

from ...actions import sync_firenze_topup
from ...extensions import db
from ...log import get_logger
from ...models import (
    GiftCard,
    GiftCardProduct,
    MinutePack,
    Order,
    OrderItemType,
    OrderStatus,
    Product,
    SubscriptionPlan,
)
from ..tarjetas.service import issue_gift_cards_for_order
from ..utils import _get_cart
from . import pagos_bp

logger = get_logger(__name__)


def _materialize_order_items(order: Order) -> list:
    """Return order items as a safe list for ORM and test doubles."""
    raw_items = getattr(order, "items", [])
    try:
        return list(raw_items)
    except TypeError:
        return []


def _summarize_order_minutes(items: list) -> int:
    """Return the total tarot minutes included in an order."""

    total_minutes = 0
    pack_ids = {item.item_id for item in items if item.item_type == OrderItemType.MINUTE_PACK.value}
    packs_by_id = {pack.id: pack.minutes for pack in MinutePack.query.filter(MinutePack.id.in_(pack_ids)).all()}

    for item in items:
        if item.item_type != OrderItemType.MINUTE_PACK.value:
            continue

        pack_minutes = packs_by_id.get(item.item_id)
        if pack_minutes is None:
            match = re.match(r"^(\d+)", item.name or "")
            pack_minutes = int(match.group(1)) if match else 0

        total_minutes += pack_minutes * int(item.quantity or 0)

    return total_minutes


# ---------------------------------------------------------------------------
# Firenze client-ID sync
# ---------------------------------------------------------------------------


def _sync_firenze_on_payment(order: Order) -> bool:
    """After payment confirmation, ensure the order (and linked user) have a Firenze client_id.

    If ``order.firenze_client_id`` is already set this is a no-op and returns
    ``True``.  Otherwise a new client is created in Firenze using the order's
    contact details.  For orders tied to a registered user that has no
    ``firenze_client_id`` the value is propagated to the user record as well.

    Returns:
        ``True`` if Firenze already had a ``client_id`` or the call succeeded,
        ``False`` if the Firenze call returned no ``client_id`` or failed.
    """
    logger.info("DO NOT USE THIS FUNCTION, use the other ones")
    return False

    from ...firenze import create_client as _firenze_create

    if order.firenze_client_id:
        logger.debug(
            f"_sync_firenze_on_payment: order={order.id} already has firenze_client_id={order.firenze_client_id}"
        )
        return True

    try:
        firenze_phone = (
            (order.user.username or "").strip()
            if order.user and order.user.username
            else (order.shipping_phone or "").strip()
        )
        logger.debug(
            f"_sync_firenze_on_payment: creating Firenze client for order={order.id} "
            f"(email={order.shipping_email!r} phone={firenze_phone!r})"
        )
        client_id = _firenze_create(
            name=order.shipping_name,
            email=order.shipping_email,
            ani=firenze_phone or None,
            transaction_id=order.transaction_id,
        )
        if client_id is not None:
            order.firenze_client_id = client_id
            logger.info(f"_sync_firenze_on_payment: created Firenze client_id={client_id} for order={order.id}")

            if order.user_id:
                from ...models import User as _User

                linked_user = db.session.get(_User, order.user_id)
                if linked_user and not linked_user.firenze_client_id:
                    linked_user.firenze_client_id = client_id
                    logger.debug(
                        f"_sync_firenze_on_payment: assigned firenze_client_id={client_id} to user={linked_user.id}"
                    )
            return True
        logger.warning(f"_sync_firenze_on_payment: no client_id returned for order={order.id}")
        return False
    except Exception:
        logger.exception(f"_sync_firenze_on_payment: failed to create Firenze client for order={order.id}")
        return False


def _send_firenze_failure_email(order: Order) -> None:
    """Backward-compatible alias for signals.send_firenze_failure_email."""
    from ...actions import send_firenze_failure_email as _send_failure

    _send_failure(order)


def _customer_wants_purchase_notification(order: Order) -> bool:
    """Return True when the customer opted into purchase notification emails."""
    user = getattr(order, "user", None)
    if user is None:
        return True

    preferences = getattr(user, "notification_preferences", None) or []
    return "purchase" in preferences


def _send_order_confirmation_email(order: Order) -> None:
    """Send order confirmation email to the customer and admin users via Daleks."""
    from daleks.contrib.client import DaleksClient

    from ...models import Role

    logger.info(f"_send_order_confirmation_email: sending confirmation emails for order={order.id}")

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(f"_send_order_confirmation_email: DALEKS_URL not configured — skipping for order={order.id}")
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    daleks_smtp_account = current_app.config.get("DALEKS_SMTP_ACCOUNT")
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

    recipient_name = order.shipping_name or order.shipping_email or ""

    # --- Customer email ---
    if order.shipping_email and _customer_wants_purchase_notification(order):
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
                    smtp_account=daleks_smtp_account,
                )
            logger.info(f"Order confirmation email sent to customer {order.shipping_email} for order={order.id}")
        except Exception:
            logger.exception(f"Failed to send order confirmation email to {order.shipping_email} for order={order.id}")
    elif order.shipping_email:
        logger.info(
            "_send_order_confirmation_email: customer opted out of purchase notifications for order=%s",
            order.id,
        )

    # --- Admin notification ---
    logger.debug(f"_send_order_confirmation_email: looking up admin role for order={order.id}")
    admin_role = Role.query.filter_by(name="admin").first()
    if admin_role:
        admin_emails = [u.email for u in admin_role.users.all() if u.active and u.email]
        if admin_emails:
            logger.debug(
                "_send_order_confirmation_email: sending admin notification to %s admin(s) for order=%s",
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
                            smtp_account=daleks_smtp_account,
                        )
                logger.info(f"Admin notification sent for order={order.id} (sent to {len(admin_emails)} admin(s))")
            except Exception:
                logger.exception(f"Failed to send admin notification for order={order.id}")
        else:
            logger.debug(f"_send_order_confirmation_email: no active admin users with email for order={order.id}")
    else:
        logger.debug(f"_send_order_confirmation_email: no admin role found in database for order={order.id}")


def _complete_succeeded_order(order: Order, label: str) -> None:
    """Shared post-payment completion logic for a ``succeeded`` order.

    Calls Firenze to register the client.  If Firenze succeeds, the order is
    marked PAID and confirmation emails are sent to the customer and admins.
    If Firenze fails, the order remains PENDING and an admin failure email is
    sent so operators can retry via the "Completar Orden" admin action.

    Args:
        order: The Order to complete (must have ``payment_status == "succeeded"``).
        label: Short context string used in log messages (e.g. ``"webhook"``).
    """
    logger.info(f"_complete_succeeded_order: processing succeeded order={order.id} from {label}")

    items = _materialize_order_items(order)
    requires_firenze = (not items) or any(item.item_type == OrderItemType.MINUTE_PACK.value for item in items)
    has_gift_cards = any(item.item_type == OrderItemType.GIFT_CARD.value for item in items)
    has_physical_products = any(item.item_type == OrderItemType.PRODUCT.value for item in items)

    if requires_firenze:
        topup_ok = False
        sync_ok = _sync_firenze_on_payment(order)
        if sync_ok:
            topup_ok, _ = sync_firenze_topup(order, automated=False)
            sync_ok = topup_ok
        if not sync_ok:
            logger.warning(
                "_complete_succeeded_order: Firenze sync failed for order=%s "
                "— order fulfillment incomplete, notifying admins",
                order.id,
            )
            db.session.commit()
            _send_firenze_failure_email(order)
            return

    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.PAID
        db.session.commit()

    if has_gift_cards:
        issued = issue_gift_cards_for_order(order)
        logger.info("_complete_succeeded_order: issued %s gift card(s) for order=%s", issued, order.id)
        if not requires_firenze and not has_physical_products:
            order.status = OrderStatus.DELIVERED
            db.session.commit()

    logger.info(
        f"_complete_succeeded_order: order={order.id} marked {order.status.upper()} "
        f"(firenze_client_id={order.firenze_client_id})"
    )
    _send_order_confirmation_email(order)


def _complete_succeeded_order_admin_flow(order: Order, label: str) -> bool:
    """Completion flow used by the admin action and webhook-finished events.

    The order is marked PAID only when Firenze sync succeeds. If Firenze fails,
    the order stays PENDING and admins are notified.
    """
    logger.info(f"_complete_succeeded_order_admin_flow: processing succeeded order={order.id} from {label}")
    items = _materialize_order_items(order)
    requires_firenze = (not items) or any(item.item_type == OrderItemType.MINUTE_PACK.value for item in items)
    has_gift_cards = any(item.item_type == OrderItemType.GIFT_CARD.value for item in items)
    has_physical_products = any(item.item_type == OrderItemType.PRODUCT.value for item in items)

    sync_ok = True
    if requires_firenze:
        sync_ok = _sync_firenze_on_payment(order)
        if sync_ok:
            topup_ok, _ = sync_firenze_topup(order, automated=False)
            sync_ok = topup_ok
    if requires_firenze and not sync_ok:
        logger.warning(
            f"_complete_succeeded_order_admin_flow: Firenze sync failed for order={order.id} — order fulfillment incomplete"
        )
        _send_firenze_failure_email(order)
        return False

    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.PAID
        db.session.commit()
    if has_gift_cards:
        issued = issue_gift_cards_for_order(order)
        logger.info("_complete_succeeded_order_admin_flow: issued %s gift card(s) for order=%s", issued, order.id)
        if not requires_firenze and not has_physical_products:
            order.status = OrderStatus.DELIVERED
            db.session.commit()
    _send_order_confirmation_email(order)
    return True


def _find_order_by_payment_id(payment_id: str) -> Order | None:
    """Return the order linked to a provider payment identifier."""
    return Order.query.filter_by(transaction_id=payment_id).first()


def _apply_payment_state_to_order(
    order: Order, *, payment_id: str, provider: str | None, state: str | None, label: str
) -> None:
    """Apply a webhook-derived payment state to an order."""
    if order.status != OrderStatus.PENDING:
        logger.debug(
            f"_apply_payment_state_to_order: order={order.id} already handled with status={order.status} "
            f"(payment_id={payment_id!r} provider={provider!r} state={state!r})"
        )
        return

    if state == "succeeded":
        _complete_succeeded_order_admin_flow(order, label)
        return

    if state in {"failed", "cancelled"}:
        order.status = OrderStatus.FAILED
        db.session.commit()
        logger.warning(
            f"_apply_payment_state_to_order: order={order.id} marked FAILED from payment_id={payment_id!r} "
            f"provider={provider!r} state={state!r}"
        )
        return

    logger.debug(
        f"_apply_payment_state_to_order: ignoring non-final event for order={order.id} "
        f"payment_id={payment_id!r} provider={provider!r} state={state!r}"
    )


def _handle_khipu_webhook_event(event) -> None:
    """Handle Khipu webhook events emitted by flask-merchants."""
    payment_id = getattr(event, "payment_id", None)
    state = getattr(getattr(event, "state", None), "value", None)
    provider = getattr(event, "provider", None)

    if not payment_id:
        logger.warning(
            f"_handle_khipu_webhook_event: missing payment_id for provider={provider!r} "
            f"event_type={getattr(event, 'event_type', None)!r}"
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            f"_handle_khipu_webhook_event: no order found for payment_id={payment_id!r} "
            f"provider={provider!r} state={state!r}"
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
            f"_handle_flow_webhook_event: missing payment_id for provider={provider!r} "
            f"event_type={getattr(event, 'event_type', None)!r}"
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            f"_handle_flow_webhook_event: no order found for payment_id={payment_id!r} provider={provider!r}"
        )
        return

    if order.status != OrderStatus.PENDING:
        logger.debug(
            f"_handle_flow_webhook_event: order={order.id} already handled with status={order.status} "
            f"(payment_id={payment_id!r})"
        )
        return

    try:
        order.sync_from_provider()
    except Exception:
        logger.exception(
            f"_handle_flow_webhook_event: failed to sync order={order.id} from provider payment_id={payment_id!r}"
        )
        return

    _apply_payment_state_to_order(
        order,
        payment_id=payment_id,
        provider=provider,
        state=order.payment_status,
        label="webhook-flow",
    )


def _handle_stripe_webhook_event(event) -> None:
    """Handle Stripe webhook events emitted by flask-merchants."""
    payment_id = getattr(event, "payment_id", None)
    state = getattr(getattr(event, "state", None), "value", None)
    provider = getattr(event, "provider", None)

    if not payment_id:
        logger.warning(
            f"_handle_stripe_webhook_event: missing payment_id for provider={provider!r} "
            f"event_type={getattr(event, 'event_type', None)!r}"
        )
        return

    order = _find_order_by_payment_id(payment_id)
    if order is None:
        logger.warning(
            f"_handle_stripe_webhook_event: no order found for payment_id={payment_id!r} "
            f"provider={provider!r} state={state!r}"
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
        f"_handle_payment_webhook_event: unsupported provider={provider!r} "
        f"event_type={getattr(event, 'event_type', None)!r} payment_id={getattr(event, 'payment_id', None)!r}"
    )


# ---------------------------------------------------------------------------
# Store index
# ---------------------------------------------------------------------------


@pagos_bp.route("/")
def index():
    """Main store page: minute packs, subscriptions, and random products."""
    logger.debug("pagos.index: loading store page")
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    subscription_plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.price).all()
    active_products = Product.query.filter_by(is_active=True).all()
    featured_products = random.sample(active_products, k=min(5, len(active_products)))
    try:
        gift_cards = GiftCardProduct.query.filter_by(is_active=True).order_by(GiftCardProduct.price).limit(4).all()
    except SQLAlchemyError:
        gift_cards = []
    cart = _get_cart()
    logger.debug(
        f"pagos.index: loaded {len(minute_packs)} minute packs, {len(subscription_plans)} subscription plans, "
        f"{len(featured_products)} random products, {len(gift_cards)} gift cards, cart_count={len(cart)}"
    )
    return render_template(
        "tienda/index.html",
        minute_packs=minute_packs,
        subscription_plans=subscription_plans,
        featured_products=featured_products,
        gift_cards=gift_cards,
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
#                         "pago_confirmacion: synced order=%s new_state=%r", order.id, order.payment_status
#                     )
#                 except Exception as sync_exc:
#                     logger.warning(
#                         "pago_confirmacion: sync_from_provider failed for order=%s — %s",
#                         order.id,
#                         sync_exc,
#                     )
#                 if order.payment_status == "succeeded":
#                     _complete_succeeded_order(order, "webhook")
#                 elif order.payment_status in ("failed", "cancelled"):
#                     order.status = OrderStatus.FAILED
#                     logger.warning(
#                         "pago_confirmacion: payment failed/cancelled — order=%s state=%r token=%r",
#                         order.id,
#                         order.payment_status,
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
        f"pago_retorno: user returned from payment (merchants_id={order_id} order={order.id} status={order.status})"
    )
    logger.debug(
        f"pago_retorno: order details — transaction_id={order.transaction_id!r} state={order.payment_status!r}"
    )

    # I DO NOT WANT TO SYNC IN THIS STAGE
    # # Sync payment state from provider and update order fulfillment status.
    # if order.transaction_id and order.status == OrderStatus.PENDING:
    #     logger.debug(f"pago_retorno: order={order.id} is PENDING, syncing from provider")
    #     try:
    #         order.sync_from_provider()
    #         logger.info(f"pago_retorno: synced order={order.id} new_state={order.payment_status!r}")
    #         if order.payment_status == "succeeded":
    #             _complete_succeeded_order(order, "retorno")
    #         elif order.payment_status in ("failed", "cancelled"):
    #             order.status = OrderStatus.FAILED
    #             logger.warning(
    #                 f"pago_retorno: payment failed/cancelled — order={order.id} "
    #                 f"status updated to FAILED (state={order.payment_status!r})"
    #             )
    #             db.session.commit()
    #     except Exception as exc:
    #         logger.error(f"pago_retorno: sync error for order={order.id} — {exc}", exc_info=True)
    # else:
    #     logger.debug(
    #         f"pago_retorno: order={order.id} not syncing "
    #         f"(has_transaction_id={bool(order.transaction_id)} status={order.status})"
    #     )

    return redirect(url_for("pagos.orden_estado", order_id=order.merchants_id))


# ---------------------------------------------------------------------------
# Order status
# ---------------------------------------------------------------------------


@pagos_bp.route("/orden/<order_id>")
def orden_estado(order_id: str):
    """Show the status of a specific order."""
    logger.debug(f"pagos.orden_estado: user checking order={order_id} status")
    order = Order.query.filter_by(merchants_id=order_id).first_or_404()
    items = _materialize_order_items(order)
    packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    try:
        issued_gift_cards = GiftCard.query.filter_by(order_id=order.id).order_by(GiftCard.id.asc()).all()
    except SQLAlchemyError:
        issued_gift_cards = []
    purchased_minutes = _summarize_order_minutes(items)
    logger.debug(f"pagos.orden_estado: order={order_id} status={order.status} has {len(items)} item(s)")
    return render_template(
        "tienda/orden_estado.html",
        order=order,
        items=items,
        packs=packs,
        issued_gift_cards=issued_gift_cards,
        purchased_minutes=purchased_minutes,
    )
