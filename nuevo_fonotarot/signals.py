"""Signal-facing post-payment processes."""

from __future__ import annotations

from typing import Any

from flask import current_app, render_template

from .extensions import db
from .firenze import post_purchase, search_client
from .log import get_logger
from .models import MinutePack, Order, OrderItemType, OrderStatus, Role, User
from .notifications import send_telegram_notification

logger = get_logger(__name__)


def _iter_order_items(order: Order) -> list[Any]:
    """Return order items as a materialized list for dynamic or eager relations."""
    items = order.items
    if hasattr(items, "all"):
        return list(items.all())
    return list(items)


def _resolve_firenze_phone(order: Order) -> str | None:
    """Pick the best phone candidate for Firenze lookup/post-purchase calls."""
    if order.user and order.user.username:
        normalized = order.user.username.strip()
        if normalized:
            return normalized
    if order.shipping_phone:
        normalized = order.shipping_phone.strip()
        if normalized:
            return normalized
    return None


def _resolve_or_lookup_client_id(order: Order) -> int | None:
    """Ensure order has a Firenze client id, reusing Firenze search when needed."""
    if order.firenze_client_id:
        return order.firenze_client_id

    firenze_phone = _resolve_firenze_phone(order)
    client_id = search_client(
        email=(order.shipping_email or None),
        phone=firenze_phone,
        ani=firenze_phone,
    )
    if client_id is not None:
        order.firenze_client_id = client_id
        logger.info(
            "post_purchase_process: resolved firenze_client_id=%s for order=%s",
            client_id,
            order.id,
        )
    else:
        logger.info(
            "post_purchase_process: no existing Firenze client found for order=%s — will create new client",
            order.id,
        )
    return client_id


def _active_admin_emails() -> list[str]:
    """Return active admin-group emails."""
    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        return []
    return [u.email for u in admin_role.users.all() if u.active and u.email]


def _send_post_purchase_success_notification(order: Order) -> None:
    """Send Telegram notification for successful post_purchase completion."""
    send_telegram_notification(
        f"post_purchase_process: Success order_id={order.id} "
        f"firenze_client_id={order.firenze_client_id}"
    )


def _send_post_purchase_admin_email(order: Order, *, audit_rows: list[dict[str, Any]]) -> None:
    """Notify all admins by email after successful post_purchase completion."""
    from daleks.contrib.client import DaleksClient

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(
            "_send_post_purchase_admin_email: DALEKS_URL not configured — skipping for order=%s",
            order.id,
        )
        return

    admin_emails = _active_admin_emails()
    if not admin_emails:
        logger.debug("_send_post_purchase_admin_email: no active admins with email")
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    daleks_smtp_account = current_app.config.get("DALEKS_SMTP_ACCOUNT")
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

    try:
        logger.info(
            "_send_post_purchase_admin_email: preparing admin email for order=%s rows=%s",
            order.id,
            len(audit_rows),
        )
        html_body = render_template(
            "tienda/email/post_purchase_admin.html",
            order=order,
            site_url=site_url,
            audit_rows=audit_rows,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            for email in admin_emails:
                client.send_email(
                    from_address=from_address,
                    to=[email],
                    subject=f"[Admin] post_purchase completed — Order #{order.id}",
                    html_body=html_body,
                    smtp_account=daleks_smtp_account,
                )
        logger.info(
            "_send_post_purchase_admin_email: sent to %s admin(s) for order=%s",
            len(admin_emails),
            order.id,
        )
    except Exception:
        logger.exception(
            "_send_post_purchase_admin_email: failed to notify admins for order=%s",
            order.id,
        )


def _associate_order_user_by_email(order: Order) -> None:
    """Link guest orders to an existing user account by order email, when possible."""
    if order.user_id:
        return

    normalized_email = (order.email or "").strip().lower()
    if not normalized_email:
        return

    linked_user = User.query.filter_by(email=normalized_email).first()
    if linked_user is None:
        logger.debug(
            "_associate_order_user_by_email: no user found for order=%s email=%r",
            order.id,
            normalized_email,
        )
        return

    order.user_id = linked_user.id
    logger.info(
        "_associate_order_user_by_email: linked order=%s to user=%s via email=%r",
        order.id,
        linked_user.id,
        normalized_email,
    )


def post_purchase_process(order_id: int) -> bool:
    """Complete the full post-purchase flow for paid minute-pack orders.

    Flow:
    - resolve/find Firenze ``client_id`` for the order
    - if not found (new customer), pass ``client_id=None`` so Firenze creates a new one
    - post each minute-pack credit in Firenze
    - if Firenze post_purchase returns ``None``, stop immediately and send Telegram error
    - if a new customer, store the client_id returned by Firenze on the order
    - if an existing customer returns a different client_id, send the mismatch alert (Telegram)
    - after successful posting, send a separate success Telegram notification
    - then send an admin email to all users in the ``admin`` group
    - finally set ``Order.status`` to ``DELIVERED`` and adopt the order user by ``Order.email``

    Args:
        order_id: Paid order identifier.

    Returns:
        ``True`` when processing completed (or nothing needed to process),
        ``False`` when the order is invalid or Firenze credits could not be posted.
    """
    if not order_id:
        logger.warning("post_purchase_process: missing order_id")
        return False

    order = db.session.get(Order, int(order_id))
    if order is None:
        logger.warning("post_purchase_process: order_id=%s not found", order_id)
        return False

    if order.payment_status != "succeeded":
        logger.warning(
            "post_purchase_process: order=%s ignored because payment_status=%r",
            order.id,
            order.payment_status,
        )
        return False

    if order.status != OrderStatus.PAID:
        logger.warning(
            "post_purchase_process: order=%s ignored because status=%r",
            order.id,
            order.status,
        )
        return False

    logger.info(
        "post_purchase_process: start order=%s payment_status=%r status=%r provider=%r transaction_id=%r",
        order.id,
        order.payment_status,
        order.status,
        order.provider,
        order.transaction_id,
    )

    # None means new customer — Firenze will create one and return the new client_id.
    client_id = _resolve_or_lookup_client_id(order)
    is_new_client = client_id is None

    item_results: list[dict[str, Any]] = []
    firenze_payloads: list[dict[str, Any]] = []
    firenze_responses: list[Any] = []
    minute_pack_processed = 0

    for item in _iter_order_items(order):
        if item.item_type != OrderItemType.MINUTE_PACK.value:
            logger.debug(
                "post_purchase_process: skipping non-minute item order=%s item_type=%r item_id=%s",
                order.id,
                item.item_type,
                item.item_id,
            )
            continue

        pack = db.session.get(MinutePack, int(item.item_id))
        if pack is None:
            logger.warning(
                "post_purchase_process: minute pack id=%s not found for order=%s",
                item.item_id,
                order.id,
            )
            item_results.append(
                {
                    "item_id": item.item_id,
                    "item_type": item.item_type,
                    "status": "missing_pack",
                }
            )
            continue

        quantity = max(int(item.quantity or 1), 1)
        seconds_to_add = int(pack.minutes) * 60 * quantity
        request_payload = {
            "client_id": client_id,
            "segundos": seconds_to_add,
            "transaction_id": order.transaction_id or str(order.id),
            "name": order.shipping_name,
            "email": order.email,
            "ani": order.shipping_phone,
        }
        logger.info(
            "post_purchase_process: post_purchase request order=%s item_id=%s payload=%r",
            order.id,
            item.item_id,
            request_payload,
        )
        post_purchase_response = post_purchase(**request_payload)
        logger.info(
            "post_purchase_process: post_purchase response order=%s item_id=%s response=%r",
            order.id,
            item.item_id,
            post_purchase_response,
        )
        firenze_payloads.append(request_payload)
        firenze_responses.append(post_purchase_response)
        posted_client_id = None
        if isinstance(post_purchase_response, dict):
            response_client_id = post_purchase_response.get("client_id")
            if response_client_id is not None:
                try:
                    posted_client_id = int(response_client_id)
                except (TypeError, ValueError):
                    logger.warning(
                        "post_purchase_process: invalid client_id in Firenze response for order=%s item_id=%s: %r",
                        order.id,
                        item.item_id,
                        response_client_id,
                    )
        row_status = "ok" if post_purchase_response is not None else "failed"
        item_results.append(
            {
                "item_id": item.item_id,
                "item_type": item.item_type,
                "quantity": quantity,
                "minutes_per_unit": int(pack.minutes),
                "seconds_posted": seconds_to_add,
                "posted_client_id": posted_client_id,
                "status": row_status,
            }
        )

        if post_purchase_response is None:
            logger.error(
                "post_purchase_process: Firenze post_purchase failed order=%s item_id=%s payload=%r",
                order.id,
                item.item_id,
                request_payload,
            )
            send_telegram_notification(
                f"post_purchase_process: ERROR order_id={order.id} item_id={item.item_id} "
                "post_purchase returned None"
            )
            order.firenze_payload = firenze_payloads
            order.firenze_response = firenze_responses
            db.session.commit()
            return False

        minute_pack_processed += 1
        if is_new_client and posted_client_id is not None:
            # Firenze created a new client — store and reuse for remaining items.
            client_id = posted_client_id
            is_new_client = False
            order.firenze_client_id = client_id
            logger.info(
                "post_purchase_process: new Firenze client created order=%s new_client_id=%s",
                order.id,
                client_id,
            )
        elif not is_new_client and posted_client_id != client_id:
            logger.error(
                "post_purchase_process: client mismatch order=%s item_id=%s expected=%s got=%s response=%r",
                order.id,
                item.item_id,
                client_id,
                posted_client_id,
                post_purchase_response,
            )
            send_telegram_notification(
                f"post_purchase_process: Clientid distinto order_id={order.id} "
                f"firenze_client_id={client_id} posted_client_id={posted_client_id}"
            )

    order.firenze_payload = firenze_payloads
    order.firenze_response = firenze_responses

    all_ok = all(result["status"] == "ok" for result in item_results)
    if item_results and all_ok:
        logger.info(
            "post_purchase_process: success notifications order=%s rows=%s",
            order.id,
            len(item_results),
        )
        _send_post_purchase_success_notification(order)
        _send_post_purchase_admin_email(order, audit_rows=item_results)
        order.status = OrderStatus.DELIVERED
        logger.info("post_purchase_process: order=%s marked DELIVERED", order.id)

    logger.info(
        "post_purchase_process: associating user by email order=%s email=%r",
        order.id,
        order.email,
    )
    _associate_order_user_by_email(order)
    db.session.commit()

    if not item_results:
        logger.info(
            "post_purchase_process: order=%s has no minute_pack items to process",
            order.id,
        )
        return True

    logger.info(
        "post_purchase_process: finished order=%s processed=%s total_items=%s all_ok=%s",
        order.id,
        minute_pack_processed,
        len(item_results),
        all_ok,
    )
    return all_ok
