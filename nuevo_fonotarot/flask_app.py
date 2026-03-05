"""Flask application factory."""

import json
import os

from flask import Flask, request, session
from flask_babel import get_locale
from flask_security.datastore import SQLAlchemyUserDatastore

from config import config
from .admin import SecureAdminIndexView, init_admin
from .extensions import (
    admin,
    babel,
    db,
    limiter,
    merchants_ext,
    migrate,
    security,
    toolbar,
)
from .utils import _FALLBACK_LANGUAGES, _LangEntry


def create_flask(config_name: str | None = None) -> Flask:
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
    toolbar.init_app(app)
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

    def _locale_selector() -> str:
        lang = session.get("lang") or request.args.get("lang")
        active = _active_locales()
        if lang:
            if lang in active:
                session["lang"] = lang
                return lang
            session.pop("lang", None)
            return default_lang
        return request.accept_languages.best_match(active, default=default_lang)

    babel.init_app(app, locale_selector=_locale_selector)
    app.jinja_env.globals["get_locale"] = get_locale

    from .models import Role, User
    import nuevo_fonotarot.extensions as _ext

    _ext.user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security.init_app(app, _ext.user_datastore)

    # TablerTheme blueprint must be registered before Admin registers its own
    # blueprint — Flask resolves templates in blueprint registration order.
    from flask_admin_tabler import TablerTheme

    theme = TablerTheme(
        theme="light",
        theme_primary="lime",
        theme_base="neutral",
        theme_radius="2",
        inter_font=True,
    )
    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=SecureAdminIndexView())
    init_admin(app, admin)

    @app.context_processor
    def inject_site_languages() -> dict:
        return {"site_languages": _parse_available_langs()}

    @app.context_processor
    def inject_current_theme() -> dict:
        """Compute the default theme based on current server time and SiteSettings.

        Reads ``dark_hours_start`` (default 20) and ``dark_hours_end`` (default 8)
        from SiteSettings.  Returns ``default_theme='dark'`` when the current hour
        falls inside that window, ``'light'`` otherwise.
        """
        from datetime import datetime

        try:
            from .models import SiteSettings

            start = int(SiteSettings.get("dark_hours_start", "20"))
            end = int(SiteSettings.get("dark_hours_end", "8"))
        except Exception:
            start, end = 20, 8

        hour = datetime.now().hour
        if start < end:
            is_dark = start <= hour < end
        else:
            # wraps midnight: e.g. start=20, end=8 → dark 20..23 and 0..7
            is_dark = hour >= start or hour < end

        return {"default_theme": "dark" if is_dark else "light"}


def _register_blueprints(app: Flask) -> None:
    from .account import account_bp
    from .content import blog_bp, content_bp
    from .lab import lab_bp
    from .legacy import legacy_bp
    from .tienda import tienda_bp

    app.register_blueprint(content_bp)
    app.register_blueprint(blog_bp, url_prefix=app.config["BLOG_URL_PREFIX"])
    app.register_blueprint(tienda_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(legacy_bp)

    from .cli import lang_cli

    app.cli.add_command(lang_cli)
