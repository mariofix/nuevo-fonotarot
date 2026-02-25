"""Flask application factory."""

import os

from flask import Flask, redirect, request, session, url_for

from flask_security.datastore import SQLAlchemyUserDatastore

from config import config
from .admin import SecureAdminIndexView, init_admin
from .extensions import admin, babel, db, limiter, migrate, security, theme

# Default languages used when the database is unavailable or empty.
_DEFAULT_LANGUAGES = [
    {"locale": "es_CL", "flag_class": "flag-country-cl", "label": "Español",  "sort_order": 0},
    {"locale": "en_US", "flag_class": "flag-country-us", "label": "English",  "sort_order": 1},
    {"locale": "pt_BR", "flag_class": "flag-country-br", "label": "Português", "sort_order": 2},
]


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

    def _active_locales() -> list[str]:
        """Return locale codes from DB, falling back to defaults."""
        try:
            from .models import SiteLanguage
            rows = SiteLanguage.query.filter_by(is_active=True).order_by(SiteLanguage.sort_order).all()
            if rows:
                return [r.locale for r in rows]
        except Exception:
            pass
        return [lang["locale"] for lang in _DEFAULT_LANGUAGES]

    # Flask-Babel: honour explicit session choice first, then Accept-Language,
    # then fall back to es_CL as the primary language.
    def _locale_selector() -> str:
        lang = session.get("lang") or request.args.get("lang")
        active = _active_locales()
        if lang and lang in active:
            session["lang"] = lang
            return lang
        return request.accept_languages.best_match(active, default=active[0])

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

    # Context processor: inject site_languages into every non-admin template.
    @app.context_processor
    def inject_site_languages() -> dict:
        try:
            from .models import SiteLanguage
            rows = SiteLanguage.query.filter_by(is_active=True).order_by(SiteLanguage.sort_order).all()
            if rows:
                return {"site_languages": rows}
        except Exception:
            pass
        # Fallback: return plain dicts that expose the same attributes via
        # attribute-style access so templates can use language.locale etc.
        class _Lang:
            def __init__(self, d):
                self.__dict__.update(d)
        return {"site_languages": [_Lang(d) for d in _DEFAULT_LANGUAGES]}


def _register_blueprints(app: Flask) -> None:
    from .blog import blog_bp
    from .home import home_bp
    from .pages import pages_bp
    from .tienda import tienda_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(tienda_bp)
