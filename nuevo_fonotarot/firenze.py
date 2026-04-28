"""Thin HTTP client for the Firenze telephony platform.

Firenze is an internal service (firenze.local) that is not accessible from
the internet.  All functions in this module are designed to be non-blocking:
they catch every exception, log a warning, and return ``None`` rather than
propagating errors to callers.

Usage::

    from nuevo_fonotarot.firenze import search_client, create_client

    client_id = search_client(email="user@example.com", phone="56912345678")
    client_id = create_client(
        name="Juan Tarot",
        email="user@example.com",
        ani="56912345678",
        transaction_id="abc123",
    )

Configuration (via ``app.config`` / environment variables)
----------------------------------------------------------
``FIRENZE_URL``
    Base URL of the Firenze API.  Defaults to ``http://firenze.local``.
``FIRENZE_TIMEOUT``
    Request timeout in seconds.  Defaults to ``5``.
"""

from urllib.parse import urljoin

import requests
from flask import current_app

from .log import get_logger

logger = get_logger(__name__)


def _base_url() -> str:
    """Return the configured Firenze base URL."""
    return current_app.config.get("FIRENZE_URL", "http://firenze.local")


def _timeout() -> int:
    """Return the configured request timeout in seconds."""
    return int(current_app.config.get("FIRENZE_TIMEOUT", 5))


def search_client(
    email: str | None = None,
    phone: str | None = None,
) -> int | None:
    """Search for an existing Firenze client by email and/or phone.

    Calls ``GET /api/v1/clients/search?service=fonotarot-cl&email=<email>&phone=<phone>``.  
    At least one of *email* or *phone* must be provided.

    Args:
        email: Customer e-mail address (optional but recommended).
        phone: Customer phone number / ANI (optional but recommended).

    Returns:
        The integer ``client_id`` from Firenze, or ``None`` if the client
        was not found or if the request failed for any reason.
    """
    if not email and not phone:
        logger.warning("firenze.search_client called with no email or phone — skipping")
        return None

    params: dict[str, str] = {}
    params["service"] = "fonotarot-cl"
    if email:
        params["email"] = email
    if phone:
        params["ani"] = phone

    url = urljoin(_base_url(), "/api/v1/clients/search")
    try:
        resp = requests.get(url, params=params, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "firenze.search_client: unexpected status %s for email=%r phone=%r",
                resp.status_code,
                email,
                phone,
            )
            return None
        data = resp.json()
        client_id = data.get("client_id")
        if client_id is not None:
            logger.debug(
                "firenze.search_client: found client_id=%s for email=%r phone=%r",
                client_id,
                email,
                phone,
            )
            return int(client_id)
        logger.debug(
            "firenze.search_client: no client_id in response for email=%r phone=%r",
            email,
            phone,
        )
        return None
    except requests.RequestException as exc:
        logger.warning(
            "firenze.search_client: network error for email=%r phone=%r — %s",
            email,
            phone,
            exc,
        )
        return None
    except Exception:
        logger.exception(
            "firenze.search_client: unexpected error for email=%r phone=%r",
            email,
            phone,
        )
        return None


def create_client(
    name: str | None,
    email: str | None,
    ani: str | None,
    transaction_id: str | None,
) -> int | None:
    """Create a new client in Firenze after a confirmed anonymous payment.

    Calls ``POST /api/v1/payments/complete`` with a JSON body containing *name*,
    *email*, *ani* (phone number), and *transaction_id*.

    Args:
        name: Customer full name (may be ``None``).
        email: Customer e-mail address (may be ``None``).
        ani: Customer phone number (may be ``None``).
        transaction_id: Payment transaction identifier for audit purposes.

    Returns:
        The integer ``client_id`` assigned by Firenze, or ``None`` if the
        request failed for any reason.
    """
    payload = {
        "service": "fonotarot-cl",
        "full_name": name or "",
        "email": email or "",
        "phone_number": ani or "",
        "ani": ani or "",
        "transaction_id": transaction_id or "",
    }
    url = urljoin(_base_url(), "/api/v1/payments/complete")
    try:
        resp = requests.post(url, json=payload, timeout=_timeout())
        if resp.status_code not in (200, 201):
            logger.warning(
                "firenze.create_client: unexpected status %s for email=%r ani=%r",
                resp.status_code,
                email,
                ani,
            )
            return None
        data = resp.json()
        client_id = data.get("client_id")
        if client_id is not None:
            logger.info(
                "firenze.create_client: created client_id=%s for email=%r ani=%r",
                client_id,
                email,
                ani,
            )
            return int(client_id)
        logger.warning(
            "firenze.create_client: no client_id in response for email=%r ani=%r",
            email,
            ani,
        )
        return None
    except requests.RequestException as exc:
        logger.warning(
            "firenze.create_client: network error for email=%r ani=%r — %s",
            email,
            ani,
            exc,
        )
        return None
    except Exception:
        logger.exception(
            "firenze.create_client: unexpected error for email=%r ani=%r",
            email,
            ani,
        )
        return None
