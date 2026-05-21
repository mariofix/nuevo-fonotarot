import json
import socket
import urllib.request
from urllib.error import URLError

import ephem

_EJECUTIVOS_URL = "https://firenze.156.cl/audiotex/ejecutivos"

# Moon phase names in order (index 0–7), matching the template display order.
MOON_PHASE_NAMES = [
    "Luna Nueva",
    "Creciente",
    "Cuarto Creciente",
    "Gibosa Creciente",
    "Luna Llena",
    "Gibosa Menguante",
    "Cuarto Menguante",
    "Menguante",
]


def get_moon_phase_index() -> int:
    """Return the current moon phase as an index from 0 to 7.

    Phases:
        0 – Luna Nueva       (New Moon)
        1 – Creciente        (Waxing Crescent)
        2 – Cuarto Creciente (First Quarter)
        3 – Gibosa Creciente (Waxing Gibbous)
        4 – Luna Llena       (Full Moon)
        5 – Gibosa Menguante (Waning Gibbous)
        6 – Cuarto Menguante (Last Quarter)
        7 – Menguante        (Waning Crescent)

    The position is derived from the fraction of the synodic cycle elapsed
    since the most recent new moon, split into 8 equal segments.
    """
    now = ephem.now()
    prev_new = ephem.previous_new_moon(now)
    next_new = ephem.next_new_moon(now)
    cycle_length = next_new - prev_new  # days (ephem dates subtract to float days)
    elapsed = now - prev_new
    position = elapsed / cycle_length  # 0.0 … <1.0
    return int(position * 8) % 8


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


_STATUS_ORDER = {"available": 0, "busy": 1, "offline": 2}


def get_agents() -> tuple[list[dict], str | None]:
    """Return ``(agents, error_code)`` from the firenze API.

    Agents are sorted available-first.  On failure returns an empty list
    with one of these error codes:

    * ``None``      — success
    * ``"timeout"`` — connection timed out (very short 1 s window)
    * ``"503"``     — HTTP or application-level error
    """
    try:
        req = urllib.request.Request(
            _EJECUTIVOS_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = json.loads(resp.read().decode())
        agents = [_normalize_agent(row) for row in data]
        return sorted(agents, key=lambda a: _STATUS_ORDER.get(a["status"], 99)), None
    except TimeoutError:
        return [], "timeout"
    except URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            return [], "timeout"
        return [], "503"
    except Exception:
        return [], "503"


def get_agent_profiles() -> tuple[list[dict], str | None]:
    """Return agent profiles for the agent cards section.

    Delegates to get_agents() so that both the hero widget and the
    agent cards section always reflect the same live data.
    """
    return get_agents()


__all__ = [
    "_flag_class",
    "_LangEntry",
    "get_agents",
    "get_agent_profiles",
    "get_moon_phase_index",
    "MOON_PHASE_NAMES",
]
