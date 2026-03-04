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


def get_agents() -> list[dict]:
    """Return the live agent list.

    Reads from Redis using a two-step pipeline (SMEMBERS + HGETALL batch).
    Falls back to placeholder data when Redis is unavailable or empty — e.g.
    during development or on a cold start before firenze has written any state.

    Redis layout expected (written by firenze):
        agents:all          → Set of option codes  {"01", "06", "15", ...}
        agent:{option}      → Hash {name, option, number, status, since}
            status values: "available" | "busy" | "offline"
    """
    try:
        import redis as redis_lib
        from flask import current_app

        r = redis_lib.from_url(
            current_app.config.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=1,
        )
        agent_ids = r.smembers("agents:all")
        if not agent_ids:
            raise LookupError("agents:all is empty — Redis has no agent state yet")

        pipe = r.pipeline()
        for aid in sorted(agent_ids):
            pipe.hgetall(f"agent:{aid}")
        return [row for row in pipe.execute() if row]

    except Exception:
        from .placeholder import AGENTS
        return list(AGENTS)


__all__ = ["_flag_class", "_LangEntry", "_FALLBACK_LANGUAGES", "get_agents"]
