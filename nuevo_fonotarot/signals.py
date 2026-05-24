"""Signal-facing post-payment processes."""

from __future__ import annotations

from typing import Any

from flask import current_app, has_app_context, render_template

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
        logger.info(f"post_purchase_process: resolved firenze_client_id={client_id} for order={order.id}")
    else:
        logger.info(
            f"post_purchase_process: no existing Firenze client found for order={order.id} — will create new client"
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
        f"post_purchase_process: Success order_id={order.id} firenze_client_id={order.firenze_client_id}"
    )


def _send_post_purchase_admin_email(order: Order, *, audit_rows: list[dict[str, Any]]) -> None:
    """Notify all admins by email after successful post_purchase completion."""
    from daleks.contrib.client import DaleksClient

    if not has_app_context():
        logger.warning(f"_send_post_purchase_admin_email: no app context — skipping for order={order.id}")
        return

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(f"_send_post_purchase_admin_email: DALEKS_URL not configured — skipping for order={order.id}")
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
            f"_send_post_purchase_admin_email: preparing admin email for order={order.id} rows={len(audit_rows)}"
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
        logger.info(f"_send_post_purchase_admin_email: sent to {len(admin_emails)} admin(s) for order={order.id}")
    except Exception:
        logger.exception(f"_send_post_purchase_admin_email: failed to notify admins for order={order.id}")


def send_firenze_failure_email(order: Order) -> None:
    """Notify admins that Firenze sync/top-up failed for a paid order."""
    from daleks.contrib.client import DaleksClient

    if not has_app_context():
        logger.warning(f"send_firenze_failure_email: no app context for order={order.id}")
        return

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(f"send_firenze_failure_email: DALEKS_URL not configured — skipping for order={order.id}")
        return

    admin_emails = _active_admin_emails()
    if not admin_emails:
        logger.debug("send_firenze_failure_email: no active admins with email")
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    daleks_smtp_account = current_app.config.get("DALEKS_SMTP_ACCOUNT")
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

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
                    smtp_account=daleks_smtp_account,
                )
        logger.info(f"send_firenze_failure_email: sent to {len(admin_emails)} admin(s) for order={order.id}")
    except Exception:
        logger.exception(f"send_firenze_failure_email: failed to notify admins for order={order.id}")


def _propagate_client_id_to_order_and_user(order: Order, client_id: int) -> None:
    """Store Firenze client_id on order and linked user (when missing on user)."""
    order.firenze_client_id = client_id
    if not order.user_id:
        return

    linked_user = db.session.get(User, int(order.user_id))
    if linked_user and not linked_user.firenze_client_id:
        linked_user.firenze_client_id = client_id
        logger.info(
            f"_propagate_client_id_to_order_and_user: assigned firenze_client_id={client_id} to user={linked_user.id}"
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
        logger.debug(f"_associate_order_user_by_email: no user found for order={order.id} email={normalized_email!r}")
        return

    order.user_id = linked_user.id
    order_client_id = getattr(order, "firenze_client_id", None)
    linked_user_client_id = getattr(linked_user, "firenze_client_id", None)
    if order_client_id and not linked_user_client_id:
        linked_user.firenze_client_id = int(order_client_id)
        logger.info(
            f"_associate_order_user_by_email: propagated firenze_client_id={order_client_id} to user={linked_user.id}"
        )
    logger.info(
        "_associate_order_user_by_email: linked order=%s to user=%s via email=%r",
        order.id,
        linked_user.id,
        normalized_email,
    )


def _sync_firenze_topup(order: Order, *, automated: bool) -> bool:
    """Run Firenze top-up sync.

    ``automated=True`` enforces the PAID safeguard used by provider/webhook
    automations. ``automated=False`` skips that state safeguard for manual/admin
    retries, while still requiring payment_status=succeeded.
    """
    if order.payment_status != "succeeded":
        logger.warning(
            f"_sync_firenze_topup: order={order.id} ignored because payment_status={order.payment_status!r}"
        )
        return False

    if automated and order.status != OrderStatus.PAID:
        logger.warning(
            f"_sync_firenze_topup: order={order.id} ignored because status={order.status!r} (automated safeguard)"
        )
        return False

    logger.info(
        f"post_purchase_process: start order={order.id} payment_status={order.payment_status!r} "
        f"status={order.status!r} provider={order.provider!r} transaction_id={order.transaction_id!r}"
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
                f"post_purchase_process: skipping non-minute item order={order.id} "
                f"item_type={item.item_type!r} item_id={item.item_id}"
            )
            continue

        pack = db.session.get(MinutePack, int(item.item_id))
        if pack is None:
            logger.warning(f"post_purchase_process: minute pack id={item.item_id} not found for order={order.id}")
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
                except TypeError, ValueError:
                    logger.warning(
                        f"post_purchase_process: invalid client_id in Firenze response for order={order.id} "
                        f"item_id={item.item_id}: {response_client_id!r}"
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
                f"post_purchase_process: Firenze post_purchase failed order={order.id} "
                f"item_id={item.item_id} payload={request_payload!r}"
            )
            send_telegram_notification(
                f"post_purchase_process: ERROR order_id={order.id} item_id={item.item_id} post_purchase returned None"
            )
            if automated:
                send_firenze_failure_email(order)
            order.firenze_payload = firenze_payloads
            order.firenze_response = firenze_responses

            return False

        minute_pack_processed += 1
        if is_new_client and posted_client_id is not None:
            # Firenze created a new client — store and reuse for remaining items.
            client_id = posted_client_id
            is_new_client = False
            _propagate_client_id_to_order_and_user(order, client_id)
            logger.info(
                f"post_purchase_process: new Firenze client created order={order.id} new_client_id={client_id}"
            )
        elif not is_new_client and posted_client_id != client_id:
            logger.error(
                f"post_purchase_process: client mismatch order={order.id} item_id={item.item_id} "
                f"expected={client_id} got={posted_client_id} response={post_purchase_response!r}"
            )
            send_telegram_notification(
                f"post_purchase_process: Clientid distinto order_id={order.id} "
                f"firenze_client_id={client_id} posted_client_id={posted_client_id}"
            )

    order.firenze_payload = firenze_payloads
    order.firenze_response = firenze_responses
    order.status = OrderStatus.DELIVERED
    db.session.flush()
    db.session.commit()
    logger.info(f"post_purchase_process: {order.id=} marked {order.status=}")

    all_ok = all(result["status"] == "ok" for result in item_results)
    if item_results and all_ok:
        logger.info(f"post_purchase_process: success notifications order={order.id} rows={len(item_results)}")
        _send_post_purchase_success_notification(order)
        _send_post_purchase_admin_email(order, audit_rows=item_results)

    logger.info(f"post_purchase_process: associating user by email order={order.id} email={order.email!r}")
    _associate_order_user_by_email(order)
    db.session.commit()

    if not item_results:
        logger.info(f"post_purchase_process: order={order.id} has no minute_pack items to process")
        return True

    logger.info(
        f"post_purchase_process: finished order={order.id} processed={minute_pack_processed} "
        f"total_items={len(item_results)} all_ok={all_ok}"
    )
    return all_ok


def sync_firenze_topup(order: Order, *, automated: bool) -> bool:
    """Public Firenze top-up sync shared by webhook and admin flows."""
    return _sync_firenze_topup(order, automated=automated)


def post_purchase_process(order_id: int) -> bool:
    """Automated post-purchase flow for paid minute-pack orders.

    This entrypoint is used by provider/webhook automation and therefore keeps
    strict safeguards:
    - requires payment_status=succeeded
    - requires fulfillment status=PAID before top-up
    - on success marks order DELIVERED and links guest orders by email
    """
    if not order_id:
        logger.warning("post_purchase_process: missing order_id")
        return False

    order = db.session.get(Order, int(order_id))
    if order is None:
        logger.warning(f"post_purchase_process: order_id={order_id} not found")
        return False

    if order.payment_status == "succeeded":
        logger.info(f"post_purchase_process: order={order.id} marked PAID")
        order.status = OrderStatus.PAID
        db.session.commit()

    logger.info(
        f"post_purchase_process: start order={order.id} "
        f"payment_status={getattr(order, 'payment_status', None)!r} "
        f"status={getattr(order, 'status', None)!r} "
        f"provider={getattr(order, 'provider', None)!r} "
        f"transaction_id={getattr(order, 'transaction_id', None)!r}"
    )

    if not _sync_firenze_topup(order, automated=True):
        return False

    logger.info(f"post_purchase_process: associating user by email order={order.id} email={order.email!r}")
    _associate_order_user_by_email(order)
    db.session.commit()
    return True
