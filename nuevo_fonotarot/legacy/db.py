"""Legacy MySQL connection helpers.

The original PHP files (conexion.php, conexionfirenze.php) had credentials
hardcoded directly in source.  This module reads them from environment
variables instead.  Set the following in your .env / environment:

    LEGACY_PORTAL_DB_URL    mysql://user:pass@host/zvn_asterisk
    LEGACY_AUDIOTEX_DB_URL  mysql://user:pass@host/zvn_audiotex_legacy
    LEGACY_FIRENZE_DB_URL   mysql://user:pass@host/zvn_firenze

The URL format is standard RFC-3986: mysql://user:password@host[:port]/dbname
"""

import os
from urllib.parse import urlparse

import pymysql
import pymysql.cursors


def _connect(env_var: str) -> pymysql.Connection:
    """Open a new pymysql DictCursor connection for the given env var URL."""
    url = os.environ.get(env_var, "")
    if not url:
        raise RuntimeError(
            f"Environment variable {env_var!r} is not set. "
            "Cannot connect to the legacy database."
        )
    parsed = urlparse(url)
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip("/"),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        charset="utf8mb4",
    )


def portal_conn() -> pymysql.Connection:
    """zvn_asterisk — CDR call records and callsprepago."""
    return _connect("LEGACY_PORTAL_DB_URL")


def audiotex_conn() -> pymysql.Connection:
    """zvn_audiotex_legacy — operators table (agent login state)."""
    return _connect("LEGACY_AUDIOTEX_DB_URL")


def firenze_conn() -> pymysql.Connection:
    """zvn_firenze — onlinecalls (live calls in progress)."""
    return _connect("LEGACY_FIRENZE_DB_URL")
