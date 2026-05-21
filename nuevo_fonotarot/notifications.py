"""Notification utilities for sending alerts via various channels."""

import os
from urllib.parse import parse_qs, urlparse

import requests

from .log import get_logger

logger = get_logger(__name__)


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
