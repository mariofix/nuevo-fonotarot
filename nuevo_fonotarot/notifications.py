"""Notification utilities for sending alerts via various channels."""

import os
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from daleks.contrib.client import DaleksClient
from flask import current_app, has_app_context, render_template

from .log import get_logger
from .models import GiftCard, Order, Role

logger = get_logger(__name__)


def _active_admin_emails() -> list[str]:
    """Return active admin-group emails."""
    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        return []
    return [u.email for u in admin_role.users.all() if u.active and u.email]


def notify_issuer_of_issued_giftcard(card: GiftCard) -> None:
    """Send an email to the giftcard purchaser"""
    if not has_app_context():
        logger.warning(f"notify_issuer_of_issued_giftcard: no app context — skipping for {card=}")
        return

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(f"notify_issuer_of_issued_giftcard: DALEKS_URL not configured — skipping for {card=}")
        return
    from json import dumps as json_dumps

    from .models import OrderItem
    from .utils import encrypt_string

    site_url = current_app.config.get("TRUSTED_HOSTS", [None])[0]
    _secret_key = current_app.config["SECRET_KEY"]
    fonotarot_url = "https://fonotarot.com"
    item = OrderItem.query.filter_by(order_id=card.order_id).first()
    payload = {"giftcard_id": card.id, "order_id": card.order_id, "item_id": item.id}
    token = encrypt_string(json_dumps(payload), _secret_key)

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    daleks_smtp_account = current_app.config.get("DALEKS_SMTP_ACCOUNT")
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")

    logger.debug(f"notify_issuer_of_issued_giftcard: preparing admin email for {card=}")
    html_body = render_template(
        "tienda/email/issued_giftcard_user.html",
        giftcard=card,
        site_url=site_url,
        fonotarot_url=fonotarot_url,
        gc_token=token,
    )

    try:
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            client.send_email(
                from_address=from_address,
                to=[card.purchaser_email],
                subject="[Fonotarot] Gracias por regalar Fonotarot",
                html_body=html_body,
                smtp_account=daleks_smtp_account,
            )
        logger.info(f"notify_issuer_of_issued_giftcard: sent to {card.purchaser_email=}")
    except Exception:
        logger.exception(f"notify_issuer_of_issued_giftcard: failed to notify purchaser for {card=}")

    return html_body


def send_post_purchase_admin_email(order: Order, *, audit_rows: list[dict[str, Any]]) -> None:
    """Notify all admins by email after successful post_purchase completion."""

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


def send_telegram_notification(message: str) -> bool:
    """Send a notification to Telegram via Watchtower webhook.

    The Telegram webhook URL format is:
    telegram://BOT_TOKEN@telegram?chats=CHAT_ID1&CHAT_ID2&preview=No

    Args:
        message: The message text to send.

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()

    if not webhook_url:
        logger.debug("send_telegram_notification: TELEGRAM_WEBHOOK_URL not configured")
        return False

    try:
        # Parse the telegram:// URL
        parsed = urlparse(webhook_url)

        if parsed.scheme != "telegram":
            logger.error(
                "send_telegram_notification: invalid webhook scheme %r (expected 'telegram')",
                parsed.scheme,
            )
            return False

        # Extract bot token from netloc (format: BOT_TOKEN@telegram)
        bot_token = parsed.netloc.split("@")[0] if "@" in parsed.netloc else parsed.netloc

        if not bot_token:
            logger.error("send_telegram_notification: bot token not found in webhook URL")
            return False

        # Parse query parameters for chat IDs and preview setting
        query_params = parse_qs(parsed.query)
        chat_ids_str = query_params.get("chats", [""])
        preview_enabled = query_params.get("preview", ["No"])[0].lower() == "yes"

        # Handle comma-separated or & separated chat IDs
        if chat_ids_str and chat_ids_str[0]:
            # If multiple IDs are passed as comma-separated string
            chat_ids = [cid.strip() for cid in chat_ids_str[0].split(",") if cid.strip()]
        else:
            # If they're passed as multiple query params
            chat_ids = [cid for cid in chat_ids_str if cid]

        if not chat_ids:
            logger.error("send_telegram_notification: no chat IDs found in webhook URL")
            return False

        # Construct Telegram Bot API URL
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        success = True
        for chat_id in chat_ids:
            try:
                response = requests.post(
                    api_url,
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "disable_web_page_preview": not preview_enabled,
                    },
                    timeout=5,
                )

                if response.status_code != 200:
                    logger.warning(
                        "send_telegram_notification: failed to send to chat_id=%s (status=%d, response=%r)",
                        chat_id,
                        response.status_code,
                        response.text,
                    )
                    success = False
                else:
                    logger.debug(
                        "send_telegram_notification: message sent to chat_id=%s",
                        chat_id,
                    )
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "send_telegram_notification: request failed for chat_id=%s (%s)",
                    chat_id,
                    str(e),
                )
                success = False

        return success

    except Exception:
        logger.exception("send_telegram_notification: unexpected error")
        return False


def notify_new_user_registration(email: str, phone: str | None = None) -> None:
    """Send a notification for a new user registration.

    Args:
        email: The email address of the new user.
        phone: Optional phone number of the new user.
    """
    phone_str = f" (teléfono: {phone})" if phone else ""
    message = f"🔔 Nuevo usuario registrado\n\nEmail: {email}{phone_str}"

    send_telegram_notification(message)


def send_new_order_admin_email(order: Order) -> None:
    """Notify all admins by email that a new order has been created (pending payment)."""
    if not has_app_context():
        logger.warning(f"send_new_order_admin_email: no app context — skipping for order={order.id}")
        return

    daleks_url = current_app.config.get("DALEKS_URL")
    if not daleks_url:
        logger.warning(f"send_new_order_admin_email: DALEKS_URL not configured — skipping for order={order.id}")
        return

    admin_emails = _active_admin_emails()
    if not admin_emails:
        logger.debug("send_new_order_admin_email: no active admins with email")
        return

    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    daleks_smtp_account = current_app.config.get("DALEKS_SMTP_ACCOUNT")
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    site_url = current_app.config.get("SITE_URL", "")

    try:
        logger.info(f"send_new_order_admin_email: preparing admin email for order={order.id}")
        html_body = render_template(
            "tienda/email/orden_creada_admin.html",
            order=order,
            site_url=site_url,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            for email in admin_emails:
                client.send_email(
                    from_address=from_address,
                    to=[email],
                    subject=f"[Admin] Nueva orden creada #{order.id} (Pendiente de pago)",
                    html_body=html_body,
                    smtp_account=daleks_smtp_account,
                )
        logger.info(f"send_new_order_admin_email: sent to {len(admin_emails)} admin(s) for order={order.id}")
    except Exception:
        logger.exception(f"send_new_order_admin_email: failed to notify admins for order={order.id}")
