"""Thin HTTP client for the Firenze telephony platform.

Firenze is an internal service (firenze.local) that is not accessible from
the internet.  All functions in this module are designed to be non-blocking:
they catch every exception, log a warning, and return ``None`` rather than
propagating errors to callers.

OAuth2 Authentication
---------------------
All API calls require a Bearer token obtained via ``POST /api/v1/auth/token``.
Tokens are cached in memory and refreshed only when expired.

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
``FIRENZE_API_USER``
    Username for OAuth2 password grant flow.
``FIRENZE_API_PASSWORD``
    Password for OAuth2 password grant flow.
``FIRENZE_TIMEOUT``
    Request timeout in seconds.  Defaults to ``5``.
"""

from time import time
from urllib.parse import urljoin

import requests
from flask import current_app

from .log import get_logger

logger = get_logger(__name__)

# Token cache: (token, expiry_time)
_token_cache: tuple[str | None, float] | None = None


def _base_url() -> str:
    """Return the configured Firenze base URL."""
    return current_app.config.get("FIRENZE_API_URL", "http://firenze.local").rstrip("/")


def _timeout() -> int:
    """Return the configured request timeout in seconds."""
    return int(current_app.config.get("FIRENZE_TIMEOUT", 5))


def _get_credentials() -> tuple[str, str] | None:
    """Return Firenze API credentials from config, or None if not configured."""
    user = current_app.config.get("FIRENZE_API_USER", "").strip()
    password = current_app.config.get("FIRENZE_API_PASSWORD", "").strip()
    if not user or not password:
        logger.warning("_get_credentials: FIRENZE_API_USER or FIRENZE_API_PASSWORD not configured")
        return None
    return (user, password)


def _fetch_token() -> str | None:
    """Fetch a new OAuth2 Bearer token from Firenze.

    Returns:
        The token string, or None if fetching failed.
    """
    creds = _get_credentials()
    if not creds:
        return None
    
    user, password = creds
    url = urljoin(_base_url(), "/api/v1/auth/token")
    payload = {
        "username": user,
        "password": password,
        "grant_type": "password",
    }
    
    logger.debug("_fetch_token: requesting token from %s", url)
    try:
        resp = requests.post(url, data=payload, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "_fetch_token: unexpected status %s from Firenze auth endpoint",
                resp.status_code,
            )
            return None
        
        data = resp.json()
        token = data.get("access_token")
        if not token:
            logger.warning("_fetch_token: no access_token in response")
            return None
        
        logger.debug("_fetch_token: obtained token successfully")
        return token
    except requests.RequestException as exc:
        logger.warning("_fetch_token: network error — %s", exc)
        return None
    except Exception:
        logger.exception("_fetch_token: unexpected error")
        return None


def _get_token() -> str | None:
    """Get a valid Bearer token, using cache if available.

    Returns:
        The token string, or None if fetching failed.
    """
    global _token_cache
    
    # Check if cached token is still valid (add 10s buffer to expiry)
    if _token_cache is not None:
        token, expiry = _token_cache
        if time() < (expiry - 10):
            logger.debug("_get_token: using cached token")
            return token
    
    logger.debug("_get_token: token cache expired or empty, fetching new token")
    token = _fetch_token()
    if token:
        # Assume 1 hour expiry (3600 seconds)
        _token_cache = (token, time() + 3600)
    else:
        _token_cache = None
    
    return token


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
        logger.warning("search_client: called with no email or phone — skipping")
        return None

    token = _get_token()
    if not token:
        logger.warning("search_client: failed to obtain authentication token")
        return None

    params: dict[str, str] = {}
    params["service"] = "fonotarot-cl"
    if email:
        params["email"] = email
    if phone:
        params["phone"] = phone

    url = urljoin(_base_url(), "/api/v1/clients/search")
    headers = {"Authorization": f"Bearer {token}"}
    
    logger.debug("search_client: searching for client (email=%r phone=%r)", email, phone)
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_timeout())
        if resp.status_code != 200:
            logger.warning(
                "search_client: unexpected status %s for email=%r phone=%r",
                resp.status_code,
                email,
                phone,
            )
            return None
        data = resp.json()
        found = data.get("found", False)
        if not found:
            logger.debug(
                "search_client: client not found for email=%r phone=%r",
                email,
                phone,
            )
            return None
        
        client_id = data.get("client_id")
        if client_id is not None:
            logger.info(
                "search_client: found client_id=%s for email=%r phone=%r",
                client_id,
                email,
                phone,
            )
            return int(client_id)
        
        logger.warning(
            "search_client: found=true but no client_id in response for email=%r phone=%r",
            email,
            phone,
        )
        return None
    except requests.RequestException as exc:
        logger.warning(
            "search_client: network error for email=%r phone=%r — %s",
            email,
            phone,
            exc,
        )
        return None
    except Exception:
        logger.exception(
            "search_client: unexpected error for email=%r phone=%r",
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
    token = _get_token()
    if not token:
        logger.warning("create_client: failed to obtain authentication token")
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
    headers = {"Authorization": f"Bearer {token}"}
    
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

