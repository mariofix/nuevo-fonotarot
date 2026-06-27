"""User-related actions that can be run independently or during lifecycle events."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from flask import current_app, has_app_context
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from .extensions import db, user_datastore
from .firenze import create_client, post_purchase, search_client
from .log import get_logger
from .models import MinutePack, Order, OrderItem, OrderItemFulfillmentStatus, OrderItemType, OrderStatus, User
from .notifications import (
    notify_new_user_registration,
    send_post_purchase_admin_email,
    send_telegram_notification,
    send_firenze_failure_email,
)

logger = get_logger(__name__)


class _CheckoutRegistrationForm:
    """Minimal form adapter for Flask-Security ``register_user``."""

    def __init__(self, email: str, phone: str) -> None:
        self._email = email
        self._phone = phone

    def to_dict(self, only_user: bool = False) -> dict:
        payload = {
            "email": self._email,
            "username": self._phone,
            "phone": self._phone,
            # Passwordless account: password is intentionally unset.
            "password": None,
        }
        return payload


def register_checkout_account(email: str, phone: str) -> tuple[User, bool]:
    """Create (or fetch) a user from checkout data using Flask-Security flow.

    This uses Flask-Security's ``register_user`` helper so standard registration
    side effects still happen (signals, confirmation token generation, welcome
    email dispatch, and unified-signin setup for email codes).

    Returns:
        A tuple ``(user, created)`` where ``created`` is ``True`` only when a
        new account was created.
    """
    from flask_security.registerable import register_user

    normalized_email = email.strip().lower()
    normalized_phone = phone.strip().lstrip("+")

    if not normalized_phone:
        raise ValueError("missing_phone")
    if not normalized_phone.isdigit() or not (10 <= len(normalized_phone) <= 13):
        raise ValueError("invalid_phone")

    existing = User.query.filter_by(email=normalized_email).first()
    if existing is not None:
        return existing, False

    form = _CheckoutRegistrationForm(email=normalized_email, phone=normalized_phone)
    try:
        user = register_user(form)
    except IntegrityError:
        db.session.rollback()
        existing_after_conflict = User.query.filter_by(email=normalized_email).first()
        if existing_after_conflict is not None:
            return existing_after_conflict, False
        raise

    db.session.commit()
    logger.info(
        "register_checkout_account: created user=%s from checkout email=%r",
        user.id,
        normalized_email,
    )
    return user, True


def _resolve_client_id_from_order(user) -> int | None:
    order = Order.query.filter(
        Order.status == "delivered",
        or_(Order.email == user.email, Order.shipping_phone == user.username),
    ).first()
    if order and order.firenze_client_id:
        logger.debug(
            "process_user_registration: resolved client_id=%s for user=%s via order=%s",
            order.firenze_client_id,
            user.id,
            order.id,
        )
        return order.firenze_client_id
    return None


def process_user_registration(user: User) -> bool:
    """Execute post-registration steps for a newly registered user.

    Performs all necessary setup after user registration, including:
    - Sending a Telegram notification about the new registration
    - Looking up and saving Firenze client_id if available
    - Adding user to 'clientes' role if client_id is found

    Args:
        user: The newly registered user.

    Returns:
        True if Firenze client_id was found and saved, False otherwise.
        Note: This returns False if no client_id was found (not an error—just
        means Firenze has no record for this user yet).
    """
    logger.info(
        "process_user_registration: starting for user=%s (email=%r phone=%r)",
        user.id,
        user.email,
        user.username,
    )

    # Send Telegram notification about new registration
    # Send to last
    changed = False
    try:
        notify_new_user_registration(email=user.email, phone=user.username)
        logger.debug(
            "process_user_registration: Telegram notification sent for user=%s",
            user.id,
        )
    except Exception:
        logger.exception(
            "process_user_registration: failed to send Telegram notification for user=%s",
            user.id,
        )

    try:
        logger.debug(
            "process_user_registration: looking up Firenze client for user=%s (email=%r phone=%r)",
            user.id,
            user.email,
            user.username,
        )

        client_id = search_client(ani=user.username) or _resolve_client_id_from_order(user)

        if client_id is None:
            logger.debug(
                "process_user_registration: no Firenze client_id found for user=%s (email=%r phone=%r)",
                user.id,
                user.email,
                user.username,
            )
            return False

        user.firenze_client_id = client_id
        changed = True
        _assign_clientes_role(user)
        db.session.commit()
        logger.info(
            "process_user_registration: saved client_id=%s and assigned 'clientes' role "
            "for user=%s (email=%r phone=%r)",
            client_id,
            user.id,
            user.email,
            user.username,
        )
        return True

    except Exception:
        if changed:
            db.session.commit()
        logger.exception(
            "process_user_registration: failed for user=%s (email=%r phone=%r)",
            user.id,
            user.email,
            user.username,
        )
        return False


def _assign_clientes_role(user: User) -> None:
    """Add user to the 'clientes' role if not already assigned.

    Args:
        user: The user to assign the 'clientes' role to.
    """
    logger.debug(
        "_assign_clientes_role: looking up 'clientes' role for user=%s",
        user.id,
    )

    clientes_role = user_datastore.find_role("clientes")
    if not clientes_role:
        logger.error(
            "_assign_clientes_role: 'clientes' role not found in database (user=%s)",
            user.id,
        )
        return

    if clientes_role not in user.roles:
        user_datastore.add_role_to_user(user, clientes_role)
        logger.info(
            "_assign_clientes_role: added 'clientes' role to user=%s",
            user.id,
        )
        logger.debug(
            "_assign_clientes_role: user=%s now has roles: %s",
            user.id,
            [role.name for role in user.roles],
        )
    else:
        logger.debug(
            "_assign_clientes_role: user=%s already has 'clientes' role",
            user.id,
        )


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
        email=(order.email or order.shipping_email),
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


def _iter_order_items(order: Order) -> list[Any]:
    """Return order items as a materialized list for dynamic or eager relations."""
    items = order.items
    if hasattr(items, "all"):
        return list(items.all())
    return list(items)


def _item_fulfillment_status(item: Any) -> str:
    status = getattr(item, "fulfillment_status", None)
    if not status:
        return OrderItemFulfillmentStatus.PENDING.value
    return str(status)


def _update_order_status_after_fulfillment(order: Order) -> None:
    items = _iter_order_items(order)
    if not items:
        return

    has_fulfillment_progress = any(
        _item_fulfillment_status(item)
        in {OrderItemFulfillmentStatus.FULFILLED.value, OrderItemFulfillmentStatus.FAILED.value}
        for item in items
    )
    has_pending = any(_item_fulfillment_status(item) != OrderItemFulfillmentStatus.FULFILLED.value for item in items)

    if has_fulfillment_progress and has_pending:
        order.status = OrderStatus.FULFILLING
    elif not has_pending:
        order.status = OrderStatus.DELIVERED


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
        _assign_clientes_role(linked_user)


def _send_post_purchase_success_notification(order: Order) -> None:
    """Send Telegram notification for successful post_purchase completion."""
    send_telegram_notification(
        f"post_purchase_process: Success order_id={order.id} firenze_client_id={order.firenze_client_id}"
    )


def _send_post_purchase_admin_email(order: Order, audit_rows: list[dict[str, Any]]) -> None:
    """Send Admin notification email for successful post_purchase completion."""
    send_post_purchase_admin_email(order=order, audit_rows=audit_rows)


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


def sync_firenze_topup(order: Order, *, automated: bool) -> tuple[bool, list]:
    """Run Firenze top-up sync.

    ``automated=True`` enforces the PAID safeguard used by provider/webhook
    automations. ``automated=False`` skips that state safeguard for manual/admin
    retries, while still requiring payment_status=succeeded.
    """
    if order.payment_status != "succeeded":
        logger.warning(
            f"_sync_firenze_topup: order={order.id} ignored because payment_status={order.payment_status!r}"
        )
        return False, []

    if automated and order.status != OrderStatus.PAID:
        logger.warning(
            f"_sync_firenze_topup: order={order.id} ignored because status={order.status!r} (automated safeguard)"
        )
        return False, []

    logger.info(
        f"post_purchase_process: start order={order.id} payment_status={order.payment_status!r} "
        f"status={order.status!r} provider={order.provider!r} transaction_id={order.transaction_id!r}"
    )

    client_id = _resolve_or_lookup_client_id(order)
    is_new_client = client_id is None

    item_results: list[dict[str, Any]] = []
    firenze_payloads: list[dict[str, Any]] = []
    firenze_responses: list[Any] = []
    minute_pack_processed = 0

    for item in _iter_order_items(order):
        if item.item_type != OrderItemType.MINUTE_PACK.value:
            logger.debug(
                f"post_purchase_process: skipping non-minute items order={order.id} "
                f"item_type={item.item_type!r} item_id={item.item_id}"
            )
            continue
        if _item_fulfillment_status(item) == OrderItemFulfillmentStatus.FULFILLED.value:
            logger.info(
                "post_purchase_process: skipping already fulfilled minute item order=%s item_id=%s",
                order.id,
                item.item_id,
            )
            continue

        pack = db.session.get(MinutePack, int(item.item_id))
        if pack is None:
            logger.warning(f"post_purchase_process: minute pack id={item.item_id} not found for order={order.id}")
            item.fulfillment_status = OrderItemFulfillmentStatus.FAILED.value
            item.fulfillment_attempts = int(getattr(item, "fulfillment_attempts", 0) or 0) + 1
            item.fulfillment_error = "minute_pack_not_found"
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
            "segundos": seconds_to_add,
            "transaction_id": order.transaction_id or str(order.id),
            "name": order.shipping_name,
            "email": order.email,
            "ani": order.shipping_phone,
        }
        if not is_new_client:
            request_payload["client_id"] = client_id

        logger.info(
            "post_purchase_process: post_purchase request order=%s item_id=%s payload=%r",
            order.id,
            item.item_id,
            request_payload,
        )
        if is_new_client:
            logger.debug(f"post_purchase_process: data to send to create_client {request_payload=}")
            firenze_post_response = create_client(**request_payload)
        else:
            firenze_post_response = post_purchase(**request_payload)
        item.fulfillment_attempts = int(getattr(item, "fulfillment_attempts", 0) or 0) + 1
        logger.info(
            "post_purchase_process: post_purchase response order=%s item_id=%s response=%r",
            order.id,
            item.item_id,
            firenze_post_response,
        )
        firenze_payloads.append(request_payload)
        firenze_responses.append(firenze_post_response)
        posted_client_id = None
        if isinstance(firenze_post_response, dict):
            response_client_id = firenze_post_response.get("client_id")
            if response_client_id is not None:
                try:
                    posted_client_id = int(response_client_id)
                except TypeError, ValueError:
                    logger.warning(
                        f"post_purchase_process: invalid client_id in Firenze response for order={order.id} "
                        f"item_id={item.item_id}: {response_client_id!r}"
                    )
        row_status = "ok" if firenze_post_response is not None else "failed"
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

        if firenze_post_response is None:
            logger.error(
                f"post_purchase_process: Firenze post_purchase failed order={order.id} "
                f"item_id={item.item_id} payload={request_payload!r}"
            )
            item.fulfillment_status = OrderItemFulfillmentStatus.FAILED.value
            item.fulfillment_error = "firenze_post_purchase_failed"
            send_telegram_notification(
                f"post_purchase_process: ERROR order_id={order.id} item_id={item.item_id} post_purchase returned None"
            )
            if automated:
                send_firenze_failure_email(order)
            order.firenze_payload = firenze_payloads
            order.firenze_response = firenze_responses
            _update_order_status_after_fulfillment(order)
            db.session.commit()

            return False, item_results

        ## Move this out of this function
        ## and after this function reports OK
        minute_pack_processed += 1
        item.fulfillment_status = OrderItemFulfillmentStatus.FULFILLED.value
        item.fulfilled_at = datetime.now()
        item.fulfillment_error = None
        item.fulfillment_reference = str(order.transaction_id or order.id)
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
                f"expected={client_id} got={posted_client_id} response={firenze_post_response!r}"
            )
            send_telegram_notification(
                f"post_purchase_process: Clientid distinto order_id={order.id} "
                f"firenze_client_id={client_id} posted_client_id={posted_client_id}"
            )
        db.session.commit()

    order.firenze_payload = firenze_payloads
    order.firenze_response = firenze_responses

    _update_order_status_after_fulfillment(order)
    db.session.flush()
    db.session.commit()
    logger.info(f"post_purchase_process: {order.id=} marked {order.status=}")

    all_ok = all(result["status"] == "ok" for result in item_results)

    ## Move this out of this function
    ## and after this function reports OK
    logger.info(f"post_purchase_process: associating user by email order={order.id} email={order.email!r}")
    _associate_order_user_by_email(order)
    db.session.commit()

    # This should not be here
    # if not item_results:
    #     logger.info(f"post_purchase_process: order={order.id} has no minute_pack items to process")
    #     return True

    logger.info(
        f"post_purchase_process: finished order={order.id} processed={minute_pack_processed} "
        f"total_items={len(item_results)} all_ok={all_ok}"
    )
    return all_ok, item_results


def _fulfill_minute_pack_order_item(order: Order, item: OrderItem) -> tuple[bool, dict[str, Any]]:
    firenze_payloads: list[dict[str, Any]] = []
    firenze_responses: list[Any] = []
    pack = db.session.get(MinutePack, int(item.item_id))
    if pack is None:
        item.fulfillment_status = OrderItemFulfillmentStatus.FAILED.value
        item.fulfillment_error = "minute_pack_not_found"
        item.fulfillment_attempts = int(getattr(item, "fulfillment_attempts", 0) or 0) + 1
        db.session.commit()
        return False, {"status": "failed", "reason": "missing_pack", "item_id": item.id}

    quantity = max(int(item.quantity or 1), 1)
    seconds_to_add = int(pack.minutes) * 60 * quantity
    client_id = order.firenze_client_id or _resolve_or_lookup_client_id(order)
    payload = {
        "segundos": seconds_to_add,
        "transaction_id": f"{order.transaction_id or order.id}:item:{item.id}",
        "name": order.shipping_name,
        "email": order.email,
        "ani": order.shipping_phone,
    }
    if client_id is not None:
        payload["client_id"] = client_id

    item.fulfillment_attempts = int(getattr(item, "fulfillment_attempts", 0) or 0) + 1
    item.fulfillment_status = OrderItemFulfillmentStatus.PROCESSING.value
    item.fulfillment_error = None
    db.session.commit()

    if client_id is None:
        response = create_client(**payload)
    else:
        response = post_purchase(**payload)

    firenze_payloads.append(payload)
    firenze_responses.append(response)

    if response is None:
        item.fulfillment_status = OrderItemFulfillmentStatus.FAILED.value
        item.fulfillment_error = "firenze_post_purchase_failed"
        db.session.commit()
        send_telegram_notification(
            f"_fulfill_minute_pack_order_item: ERROR order_id={order.id} item_id={item.item_id} response returned None"
        )

        send_firenze_failure_email(order)
        return False, {"status": "failed", "reason": "firenze_post_purchase_failed", "item_id": item.id}

    posted_client_id = None
    if isinstance(response, dict) and response.get("client_id") is not None:
        try:
            posted_client_id = int(response["client_id"])
        except TypeError, ValueError:
            posted_client_id = None

    if posted_client_id is not None and order.firenze_client_id is None:
        _propagate_client_id_to_order_and_user(order, posted_client_id)

    item.fulfillment_status = OrderItemFulfillmentStatus.FULFILLED.value
    item.fulfilled_at = datetime.now()
    item.fulfillment_error = None
    item.fulfillment_reference = str(payload["transaction_id"])
    order.firenze_payload = firenze_payloads
    order.firenze_response = firenze_responses
    db.session.commit()
    return True, {"status": "ok", "item_id": item.id, "seconds_posted": seconds_to_add}


def fulfill_single_order_item(order_id: int, order_item_id: int) -> dict[str, Any]:
    """Fulfill one order item by type, with item-level idempotency."""
    order = db.session.get(Order, int(order_id))
    item = db.session.get(OrderItem, int(order_item_id))
    if order is None or item is None or item.order_id != int(order_id):
        return {
            "status": "failed",
            "reason": "order_or_item_not_found",
            "order_id": order_id,
            "item_id": order_item_id,
        }
    if order.payment_status != "succeeded":
        return {"status": "failed", "reason": "payment_not_succeeded", "order_id": order.id, "item_id": item.id}
    if _item_fulfillment_status(item) == OrderItemFulfillmentStatus.FULFILLED.value:
        return {"status": "skipped", "reason": "already_fulfilled", "order_id": order.id, "item_id": item.id}

    if item.item_type == OrderItemType.MINUTE_PACK.value:
        ok, detail = _fulfill_minute_pack_order_item(order, item)
    elif item.item_type == OrderItemType.GIFT_CARD.value:
        # Lazy import avoids circular imports during app startup.
        from .tienda.tarjetas.service import issue_gift_cards_for_order_item

        ok, detail = issue_gift_cards_for_order_item(order, item)
    else:
        return {"status": "skipped", "reason": "unsupported_item_type", "order_id": order.id, "item_id": item.id}

    _update_order_status_after_fulfillment(order)
    db.session.commit()
    detail["order_id"] = order.id
    detail["item_type"] = item.item_type
    detail["ok"] = ok
    return detail


def _run_single_item_worker(app, order_id: int, order_item_id: int) -> dict[str, Any]:
    with app.app_context():
        return fulfill_single_order_item(order_id=order_id, order_item_id=order_item_id)


def dispatch_order_fulfillment_async(
    order_id: int,
    *,
    max_workers: int = 4,
    retry_statuses: tuple[str, ...] = (
        OrderItemFulfillmentStatus.PENDING.value,
        OrderItemFulfillmentStatus.FAILED.value,
    ),
) -> dict[str, Any]:
    """Fan out item fulfillment in parallel for minute packs and gift cards."""
    if not has_app_context():
        raise RuntimeError("dispatch_order_fulfillment_async requires an app context")

    order = db.session.get(Order, int(order_id))
    if order is None:
        return {"status": "failed", "reason": "order_not_found", "order_id": order_id}
    if order.payment_status != "succeeded":
        return {"status": "failed", "reason": "payment_not_succeeded", "order_id": order.id}

    dispatchable_types = {OrderItemType.MINUTE_PACK.value, OrderItemType.GIFT_CARD.value}
    item_ids = [
        int(item.id)
        for item in _iter_order_items(order)
        if item.item_type in dispatchable_types and _item_fulfillment_status(item) in retry_statuses
    ]
    if not item_ids:
        _update_order_status_after_fulfillment(order)
        db.session.commit()
        return {"status": "ok", "order_id": order.id, "scheduled": 0, "results": []}

    order.status = OrderStatus.FULFILLING
    db.session.commit()
    app = current_app._get_current_object()  # type: ignore

    results: list[dict[str, Any]] = []
    worker_count = max(1, min(int(max_workers), len(item_ids)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_run_single_item_worker, app, int(order.id), item_id) for item_id in item_ids]
        for future in as_completed(futures):
            results.append(future.result())

    refreshed_order = db.session.get(Order, int(order.id))
    if refreshed_order is not None:
        _update_order_status_after_fulfillment(refreshed_order)
        db.session.commit()

    return {
        "status": "ok",
        "order_id": order.id,
        "scheduled": len(item_ids),
        "results": results,
    }


def post_purchase_process(
    order_id: int | None = None,
    transaction_id: str | None = None,
) -> bool:
    """post-purchase flow for succesful payment webhook for (currently) minute_packs

    This entrypoint is used by provider/webhook automation and therefore keeps
    strict safeguards:
    - requires payment_status=succeeded
    - requires fulfillment status=PAID before executing
    - If minute pack,
        - top-up firenze account.
        - propagate client_id when required
    - on success marks order DELIVERED, links guest orders by email, sends user notification if set
    - notifies admin group via mail and/or telegram
    """
    if not order_id and not transaction_id:
        logger.warning("post_purchase_process: missing order_id or transaction_id")
        return False

    order = None
    if order_id:
        order = db.session.get(Order, int(order_id))
    if transaction_id:
        order = Order.query.filter_by(transaction_id=transaction_id).first()

    if order is None:
        logger.warning(f"post_purchase_process: {order_id=}/{transaction_id=} not found")
        return False

    logger.debug(f"post_purchase_process: {order} found")
    if order.payment_status == "succeeded":
        order.status = OrderStatus.PAID
        db.session.flush()
        logger.info(f"post_purchase_process: {order.id=} marked PAID")

    logger.info(
        f"post_purchase_process: starting fullfillment for {order.id=} {order.transaction_id} "
        f" {order.payment_status=} {order.status=} {order.provider=}"
    )

    # topup, _ = sync_firenze_topup(order, automated=True)
    # if not topup:
    #     logger.warning("post_purchase_process: sync_firenze_topup returned False")
    fulfill = dispatch_order_fulfillment_async(order_id=order.id)
    logger.debug(f"post_purchase_process: fulfilling result {fulfill=}")

    if fulfill.get("status", False) == "ok":
        logger.info(f"post_purchase_process: success notifications order={order.id} rows={len(fulfill["results"])}")
        ## Move this out of this function
        ## and after this function reports OK
        _send_post_purchase_success_notification(order)
        _send_post_purchase_admin_email(order, audit_rows=fulfill["results"])
    logger.info(f"post_purchase_process: associating user by email order={order.id} email={order.email!r}")
    _associate_order_user_by_email(order)
    db.session.commit()
    return True
