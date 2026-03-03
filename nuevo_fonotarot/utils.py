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
