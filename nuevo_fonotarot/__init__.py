"""Flask application factory."""

import json
import os

from flask import Flask, redirect, request, session, url_for

from flask_security.datastore import SQLAlchemyUserDatastore

from config import config
from .admin import SecureAdminIndexView, init_admin
from .extensions import admin, babel, db, limiter, merchants_ext, migrate, security, theme

# Fallback language list used when the DB is unavailable or the
# ``available_lang`` setting has not been seeded yet.
# Format: [short_code, locale, label]
_FALLBACK_LANGUAGES = [
    ["es", "es_CL", "Español"],
    ["en", "en_US", "English"],
    ["pt", "pt_BR", "Português"],
]


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


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_name: One of ``development``, ``production``, or ``testing``.
                     Defaults to the ``FLASK_ENV`` environment variable, or
                     ``development`` when not set.
    """
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    _init_extensions(app)
    _register_blueprints(app)

    return app


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    default_lang: str = app.config.get("DEFAULT_LANGUAGE", "es_CL")

    def _parse_available_langs() -> list[_LangEntry]:
        """Return language entries from SiteSettings, falling back to defaults."""
        try:
            from .models import SiteSettings
            raw = SiteSettings.get("available_lang")
            if raw:
                return [_LangEntry(*item) for item in json.loads(raw)]
        except Exception:
            pass
        return [_LangEntry(*item) for item in _FALLBACK_LANGUAGES]

    def _active_locales() -> list[str]:
        return [lang.locale for lang in _parse_available_langs()]

    # Flask-Babel: honour explicit session choice first, then Accept-Language,
    # then fall back to DEFAULT_LANGUAGE.
    def _locale_selector() -> str:
        lang = session.get("lang") or request.args.get("lang")
        active = _active_locales()
        if lang:
            if lang in active:
                session["lang"] = lang
                return lang
            # Explicit lang code requested but not available → clear stale
            # session value and show the site in Spanish (primary language).
            session.pop("lang", None)
            return default_lang
        return request.accept_languages.best_match(active, default=default_lang)

    babel.init_app(app, locale_selector=_locale_selector)

    # Expose get_locale() in every template.
    from flask_babel import get_locale
    app.jinja_env.globals["get_locale"] = get_locale

    # Flask-Security: set up user datastore and initialise extension.
    from .models import Role, User

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security.init_app(app, user_datastore)

    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=SecureAdminIndexView())

    init_admin(app, admin)

    # Initialise flask-merchants with Flow and Khipu providers.
    _init_merchants(app)

    # Context processor: inject site_languages into every non-admin template.
    @app.context_processor
    def inject_site_languages() -> dict:
        return {"site_languages": _parse_available_langs()}


def _init_merchants(app: Flask) -> None:
    """Configure flask-merchants with Flow and Khipu providers."""
    from .providers import FlowProvider, KhipuProvider

    flow_provider = FlowProvider(
        api_key=app.config.get("FLOW_API_KEY", ""),
        api_secret=app.config.get("FLOW_SECRET_KEY", ""),
        api_url=app.config.get("FLOW_API_URL", "https://sandbox.flow.cl/api"),
        subject="Fonotarot – Compra",
        confirmation_url="",  # will be set per-request via metadata
    )
    khipu_provider = KhipuProvider(
        api_key=app.config.get("KHIPU_API_KEY", ""),
        subject="Fonotarot – Compra",
    )

    from .models import Payment

    merchants_ext.init_app(
        app,
        providers=[flow_provider, khipu_provider],
        db=db,
        models=[Payment],
        admin=admin,
    )


def _register_blueprints(app: Flask) -> None:
    from .blog import blog_bp
    from .home import home_bp
    from .pages import pages_bp
    from .tienda import tienda_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(tienda_bp)

    from .cli import lang_cli
    app.cli.add_command(lang_cli)
