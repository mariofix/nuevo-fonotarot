"""Thin HTTP client for the Firenze telephony platform.

Firenze is an internal service (firenze.local) that is not accessible from
the internet.  All functions in this module are designed to be non-blocking:
they catch every exception, log a warning, and return ``None`` rather than
propagating errors to callers.

Header Authentication
---------------------
Protected API calls use ``x-api-key`` and ``x-api-secret`` headers.

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
``FIRENZE_API_URL``
    Base URL of the Firenze API.  Defaults to ``http://firenze.local``.
``FIRENZE_API_KEY``
    API key used in ``x-api-key`` request header.
``FIRENZE_API_SECRET``
    API secret used in ``x-api-secret`` request header.
``FIRENZE_API_TIMEOUT``
    Request timeout in seconds.  Defaults to ``5``.
"""

from urllib.parse import urljoin

import requests
from flask import current_app

from .log import get_logger

logger = get_logger(__name__)

def _base_url() -> str:
    """Return the configured Firenze base URL."""
    return current_app.config.get("FIRENZE_API_URL", "http://firenze.local").rstrip("/")


def _timeout() -> int:
    """Return the configured request timeout in seconds."""
    return int(current_app.config.get("FIRENZE_API_TIMEOUT", current_app.config.get("FIRENZE_TIMEOUT", 5)))


def _get_credentials() -> tuple[str, str] | None:
    """Return Firenze API credentials from config, or None if not configured."""
    api_key = (
        current_app.config.get("FIRENZE_API_KEY", "")
        or current_app.config.get("FIRENZE_API_USER", "")
    ).strip()
    api_secret = (
        current_app.config.get("FIRENZE_API_SECRET", "")
        or current_app.config.get("FIRENZE_API_PASSWORD", "")
    ).strip()
    if not api_key or not api_secret:
        logger.warning("_get_credentials: FIRENZE_API_KEY or FIRENZE_API_SECRET not configured")
        return None
    return (api_key, api_secret)


def _auth_headers() -> dict[str, str] | None:
    """Return authentication headers for Firenze API calls."""
    creds = _get_credentials()
    if not creds:
        return None
    api_key, api_secret = creds
    return {
        "x-api-key": api_key,
        "x-api-secret": api_secret,
    }


def search_client(
    client_id: int | str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> int | None:
    """Search for an existing Firenze client by client_id/email/phone.

    Calls ``GET /api/v1/clients/search`` with ``service=fonotarot-cl`` and one
    or more lookup fields (``client_id``, ``email``, ``phone``).

    Args:
        client_id: Firenze client identifier (preferred when known).
        email: Customer e-mail address (optional but recommended).
        phone: Customer phone number / ANI (optional but recommended).

    Returns:
        The integer ``client_id`` from Firenze, or ``None`` if the client
        was not found or if the request failed for any reason.
    """
    normalized_client_id = str(client_id).strip() if client_id is not None else ""
    if not normalized_client_id and not email and not phone:
        logger.warning("search_client: called with no client_id/email/phone — skipping")
        return None

    headers = _auth_headers()
    if not headers:
        logger.warning("search_client: missing Firenze API credentials")
        return None

    params: dict[str, str] = {}
    params["service"] = "fonotarot-cl"
    if normalized_client_id:
        params["client_id"] = normalized_client_id
    if email:
        params["email"] = email
    if phone:
        params["phone"] = phone

    url = urljoin(_base_url(), "/api/v1/clients/search")
    logger.debug(
        "search_client: searching for client (client_id=%r email=%r phone=%r)",
        normalized_client_id or None,
        email,
        phone,
    )
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "search_client: unexpected status %s for client_id=%r email=%r phone=%r",
                resp.status_code,
                normalized_client_id or None,
                email,
                phone,
            )
            return None
        data = resp.json()
        found = data.get("found", False)
        if not found:
            logger.debug(
                "search_client: client not found for client_id=%r email=%r phone=%r",
                normalized_client_id or None,
                email,
                phone,
            )
            return None
        
        client_id = data.get("client_id")
        if client_id is not None:
            logger.info(
                "search_client: found client_id=%s for lookup client_id=%r email=%r phone=%r",
                client_id,
                normalized_client_id or None,
                email,
                phone,
            )
            return int(client_id)
        
        logger.warning(
            "search_client: found=true but no client_id in response for lookup client_id=%r email=%r phone=%r",
            normalized_client_id or None,
            email,
            phone,
        )
        return None
    except requests.RequestException as exc:
        logger.warning(
            "search_client: network error for client_id=%r email=%r phone=%r — %s",
            normalized_client_id or None,
            email,
            phone,
            exc,
        )
        return None
    except Exception:
        logger.exception(
            "search_client: unexpected error for client_id=%r email=%r phone=%r",
            normalized_client_id or None,
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

    Calls ``POST /api/v1/payments/complete`` with a JSON body containing profile
    information and payment transaction identifier.

    Args:
        name: Customer full name (may be ``None``).
        email: Customer e-mail address (may be ``None``).
        ani: Customer phone number (may be ``None``).
        transaction_id: Payment transaction identifier for audit purposes.

    Returns:
        The integer ``client_id`` assigned by Firenze, or ``None`` if the
        request failed for any reason.
    """
    headers = _auth_headers()
    if not headers:
        logger.warning("create_client: missing Firenze API credentials")
        return None

    payload = {
        "service": "fonotarot-cl",
        "full_name": name or "",
        "email": email or "",
        "phone_number": ani or "",
        "ani": ani or "",
        "transaction_id": transaction_id or "",
    }
    
    url = urljoin(_base_url(), "/api/v1/payments/complete")
    logger.debug(
        "create_client: creating client (name=%r email=%r ani=%r transaction_id=%r)",
        name,
        email,
        ani,
        transaction_id,
    )
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_timeout())
        if resp.status_code not in (200, 201):
            logger.warning(
                "create_client: unexpected status %s for email=%r ani=%r transaction_id=%r",
                resp.status_code,
                email,
                ani,
                transaction_id,
            )
            return None
        
        data = resp.json()
        client_id = data.get("client_id")
        if client_id is not None:
            logger.info(
                "create_client: created client_id=%s for email=%r ani=%r transaction_id=%r",
                client_id,
                email,
                ani,
                transaction_id,
            )
            return int(client_id)
        
        logger.warning(
            "create_client: no client_id in response for email=%r ani=%r transaction_id=%r",
            email,
            ani,
            transaction_id,
        )
        return None
    except requests.RequestException as exc:
        logger.warning(
            "create_client: network error for email=%r ani=%r — %s",
            email,
            ani,
            exc,
        )
        return None
    except Exception:
        logger.exception(
            "create_client: unexpected error for email=%r ani=%r",
            email,
            ani,
        )
        return None


def _int_from(value: object) -> int | None:
    """Parse an integer from *value* when possible."""
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_minutes_from_client_search(payload: dict) -> int | None:
    """Return available minutes from a Firenze client-search payload.

    Firenze deployments can expose credit balance with slightly different key
    names. This helper checks common minute and second fields and normalises
    the output to minutes.
    """
    minute_keys = (
        "minutes",
        "minutos",
        "available_minutes",
        "remaining_minutes",
        "credit_minutes",
    )
    second_keys = (
        "seconds",
        "segundos",
        "available_seconds",
        "remaining_seconds",
        "credits",
        "creditos",
    )

    sources = [payload]
    for key in ("client", "data", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    for source in sources:
        for key in minute_keys:
            minutes = _int_from(source.get(key))
            if minutes is not None:
                return max(0, minutes)
        for key in second_keys:
            seconds = _int_from(source.get(key))
            if seconds is not None:
                return max(0, seconds // 60)

    return None


def search_client_minutes_by_email(email: str) -> tuple[int | None, str | None]:
    """Return `(minutes, error_code)` for a Firenze client searched by email.

    The lookup intentionally uses only the email address.
    Error codes:
    - ``auth``: missing Firenze API credentials
    - ``503``: request/response failure to Firenze
    - ``None``: request succeeded (minutes may still be None if not found)
    """
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None, None

    return search_client_minutes(client_id=None, email=normalized_email)


def search_client_minutes(
    *,
    client_id: int | None = None,
    email: str | None = None,
) -> tuple[int | None, str | None]:
    """Return ``(minutes, error_code)`` from Firenze using client_id or email.

    Lookup preference:
    1. ``client_id`` when provided.
    2. ``email`` as fallback when ``client_id`` is absent.

    Error codes:
    - ``auth``: missing Firenze API credentials
    - ``503``: request/response failure to Firenze
    - ``None``: request succeeded (minutes may still be None if not found)
    """
    normalized_email = (email or "").strip().lower()
    normalized_client_id = int(client_id) if client_id is not None else None
    if normalized_client_id is None and not normalized_email:
        return None, None

    headers = _auth_headers()
    if not headers:
        logger.warning("search_client_minutes: missing Firenze API credentials")
        return None, "auth"

    url = urljoin(_base_url(), "/api/v1/clients/search")
    params: dict[str, str | int] = {"service": "fonotarot-cl"}
    if normalized_client_id is not None:
        params["client_id"] = normalized_client_id
    else:
        params["email"] = normalized_email

    logger.debug(
        "search_client_minutes: searching credits for client_id=%r email=%r",
        normalized_client_id,
        normalized_email,
    )
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "search_client_minutes: unexpected status=%s for client_id=%r email=%r",
                resp.status_code,
                normalized_client_id,
                normalized_email,
            )
            return None, "503"

        payload = resp.json()
        if not payload.get("found", False):
            return None, None

        return _extract_minutes_from_client_search(payload), None
    except requests.RequestException as exc:
        logger.warning(
            "search_client_minutes: network error for client_id=%r email=%r — %s",
            normalized_client_id,
            normalized_email,
            exc,
        )
        return None, "503"
    except Exception:
        logger.exception(
            "search_client_minutes: unexpected error for client_id=%r email=%r",
            normalized_client_id,
            normalized_email,
        )
        return None, "503"


_UNSET = object()


def _normalize_ani(ani: str | None) -> str | None:
    """Return a normalized ANI string (digits only, length 8-15)."""
    if not ani:
        return None
    normalized = "".join(ch for ch in ani if ch.isdigit())
    if 8 <= len(normalized) <= 15:
        return normalized
    return None


def update_client_profile(
    client_id: int,
    *,
    service: str = "fonotarot-cl",
    full_name: str | None | object = _UNSET,
    phone: str | None | object = _UNSET,
) -> bool:
    """Update a Firenze client profile with changed local user fields.

    Only fields explicitly passed are sent to Firenze. Passing ``phone=None``
    clears registered ANI values using the Firenze ``::EMPTY::`` sentinel.
    """
    payload: dict[str, str | None] = {}
    if full_name is not _UNSET:
        payload["full_name"] = None if full_name is None else str(full_name)
    if phone is not _UNSET:
        payload["phone"] = "::EMPTY::" if phone is None else str(phone)

    if not payload:
        return True

    headers = _auth_headers()
    if not headers:
        logger.warning(
            "update_client_profile: missing Firenze API credentials for client_id=%s",
            client_id,
        )
        return False

    url = urljoin(_base_url(), f"/api/v1/clients/{service}/{client_id}")

    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "update_client_profile: unexpected status=%s for client_id=%s payload=%s body=%r",
                resp.status_code,
                client_id,
                payload,
                resp.text[:300],
            )
            return False
        return True
    except requests.RequestException as exc:
        logger.warning(
            "update_client_profile: network error for client_id=%s payload=%s — %s",
            client_id,
            payload,
            exc,
        )
        return False


def list_client_anis(client_id: int, *, service: str = "fonotarot-cl") -> list[str] | None:
    """Return ANI list for a Firenze client, or None when request fails."""
    headers = _auth_headers()
    if not headers:
        logger.warning("list_client_anis: missing Firenze API credentials for client_id=%s", client_id)
        return None

    url = urljoin(_base_url(), f"/api/v1/client-ani/{service}/{client_id}")

    try:
        resp = requests.get(url, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "list_client_anis: unexpected status=%s for client_id=%s body=%r",
                resp.status_code,
                client_id,
                resp.text[:300],
            )
            return None

        payload = resp.json()
        anis = payload.get("anis", [])
        if not isinstance(anis, list):
            logger.warning("list_client_anis: unexpected anis payload type for client_id=%s", client_id)
            return None

        normalized = [_normalize_ani(str(item)) for item in anis]
        return [ani for ani in normalized if ani]
    except requests.RequestException as exc:
        logger.warning("list_client_anis: network error for client_id=%s — %s", client_id, exc)
        return None
    except Exception:
        logger.exception("list_client_anis: unexpected error for client_id=%s", client_id)
        return None


def add_client_ani(
    client_id: int,
    ani: str,
    *,
    service: str = "fonotarot-cl",
) -> tuple[bool, bool]:
    """Add ANI to a Firenze client.

    Returns ``(success, created)``.
    """
    normalized_ani = _normalize_ani(ani)
    if not normalized_ani:
        logger.warning("add_client_ani: invalid ANI value for client_id=%s", client_id)
        return False, False

    headers = _auth_headers()
    if not headers:
        logger.warning("add_client_ani: missing Firenze API credentials for client_id=%s", client_id)
        return False, False

    url = urljoin(_base_url(), "/api/v1/client-ani/create")
    payload = {
        "service": service,
        "client_id": int(client_id),
        "ani": normalized_ani,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_timeout())
        if resp.status_code not in (200, 201):
            logger.warning(
                "add_client_ani: unexpected status=%s for client_id=%s payload=%s body=%r",
                resp.status_code,
                client_id,
                payload,
                resp.text[:300],
            )
            return False, False

        data = resp.json()
        return bool(data.get("ok", True)), bool(data.get("created", False))
    except requests.RequestException as exc:
        logger.warning("add_client_ani: network error for client_id=%s ani=%s — %s", client_id, normalized_ani, exc)
        return False, False
    except Exception:
        logger.exception("add_client_ani: unexpected error for client_id=%s ani=%s", client_id, normalized_ani)
        return False, False


def delete_client_ani(
    client_id: int,
    ani: str,
    *,
    service: str = "fonotarot-cl",
) -> tuple[bool, bool]:
    """Delete ANI from a Firenze client.

    Returns ``(success, deleted)``.
    """
    normalized_ani = _normalize_ani(ani)
    if not normalized_ani:
        logger.warning("delete_client_ani: invalid ANI value for client_id=%s", client_id)
        return False, False

    headers = _auth_headers()
    if not headers:
        logger.warning("delete_client_ani: missing Firenze API credentials for client_id=%s", client_id)
        return False, False

    url = urljoin(_base_url(), f"/api/v1/client-ani/{service}/{client_id}/{normalized_ani}")

    try:
        resp = requests.delete(url, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "delete_client_ani: unexpected status=%s for client_id=%s ani=%s body=%r",
                resp.status_code,
                client_id,
                normalized_ani,
                resp.text[:300],
            )
            return False, False

        data = resp.json()
        return bool(data.get("ok", True)), bool(data.get("deleted", False))
    except requests.RequestException as exc:
        logger.warning("delete_client_ani: network error for client_id=%s ani=%s — %s", client_id, normalized_ani, exc)
        return False, False
    except Exception:
        logger.exception("delete_client_ani: unexpected error for client_id=%s ani=%s", client_id, normalized_ani)
        return False, False
