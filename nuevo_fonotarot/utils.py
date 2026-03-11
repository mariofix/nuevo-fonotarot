import json
import urllib.request
from urllib.error import URLError

_EJECUTIVOS_URL = "https://firenze.156.cl/audiotex/ejecutivos"


def _flag_class(locale: str) -> str:
    """Derive a Tabler flag CSS class from a locale string.

    ``es_CL`` → ``flag-country-cl``
    """
    territory = locale.split("_")[-1].lower()
    return f"flag-country-{territory}"


class _LangEntry:
    """Simple value object exposing the language attributes templates expect."""

    def __init__(self, short: str, locale: str, label: str) -> None:
        self.short = short
        self.locale = locale
        self.label = label
        self.flag_class = _flag_class(locale)

    def __repr__(self) -> str:
        return f"<_LangEntry {self.locale}>"


# Fallback language list used when the DB is unavailable or the
# ``available_lang`` setting has not been seeded yet.
# Format: [short_code, locale, label]
_FALLBACK_LANGUAGES = [
    ["es", "es_CL", "Español"],
    ["en", "en_US", "English"],
    ["pt", "pt_BR", "Português"],
]


def _normalize_agent(raw: dict) -> dict:
    """Map a firenze API agent record to the dict shape templates expect.

    Firenze fields:
        nombre      → name
        opcion      → option  (zero-padded string: "01", "15", …)
        ingreso     → logged-in flag
        disponible  → availability flag
        descripcion → description

    Derived:
        number  = "7" + zero-padded opcion  ("7001", "7015", …)
        status  = "available" | "busy" | "offline"
    """
    opcion = int(raw.get("opcion", 0))
    ingreso = bool(raw.get("ingreso", False))
    disponible = bool(raw.get("disponible", False))

    if not ingreso:
        status = "offline"
    elif disponible:
        status = "available"
    else:
        status = "busy"

    return {
        "name": raw.get("nombre", ""),
        "option": f"{opcion:02d}",
        "number": f"7{opcion:03d}",
        "status": status,
        "description": raw.get("descripcion", ""),
    }


def get_agents() -> list[dict]:
    """Return the live agent list from the firenze API.

    Falls back to placeholder data when the API is unavailable — e.g.
    during development or a network outage.
    """
    try:
        req = urllib.request.Request(
            _EJECUTIVOS_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        return [_normalize_agent(row) for row in data]
    except Exception:
        from .placeholder import AGENTS
        return list(AGENTS)


def get_agent_profiles() -> list[dict]:
    """Return agent profiles for the agent cards section.

    Delegates to get_agents() so that both the hero widget and the
    agent cards section always reflect the same live data.
    """
    return get_agents()


__all__ = [
    "_flag_class", "_LangEntry", "_FALLBACK_LANGUAGES",
    "get_agents", "get_agent_profiles",
]
