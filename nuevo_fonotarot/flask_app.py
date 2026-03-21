"""Flask application factory."""

import logging.config
import os
from typing import Any

from flask import Flask, request, session
from flask_babel import get_locale
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config
from .admin import SecureAdminIndexView, init_admin
from .extensions import (
    admin,
    babel,
    csrf,
    db,
    limiter,
    merchants_ext,
    migrate,
    security,
    toolbar,
)
from .utils import _LangEntry


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
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Apply Django-style logging configuration from the LOGGING config key.
    # All nuevo_fonotarot.* loggers inherit from the 'nuevo_fonotarot' root
    # logger defined in the LOGGING dict.  Override verbosity with LOG_LEVEL.
    logging.config.dictConfig(app.config["LOGGING"])

    _init_extensions(app)
    _register_blueprints(app)
    _init_merchants(app, admin=admin)

    site_domain = app.config.get("TRUSTED_HOSTS", ["localhost"])[0]
    app.jinja_env.globals["site_domain"] = site_domain
    app.jinja_env.globals["site_url"] = f"https://{site_domain}"

    return app


def _init_extensions(app: Flask) -> None:
    csrf.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    toolbar.init_app(app)
    available_langs: list = app.config.get(
        "AVAILABLE_LANGUAGES", [["es", "es_CL", "Español"]]
    )

    def _parse_available_langs() -> list[_LangEntry]:
        """Return language entries from app config."""
        return [_LangEntry(*item) for item in available_langs]

    def _active_locales() -> list[str]:
        return [lang.locale for lang in _parse_available_langs()]

    def _locale_selector() -> str:
        lang = session.get("lang") or request.args.get("lang")
        active = _active_locales()
        # SiteSettings overrides the deploy-time BABEL_DEFAULT_LOCALE if set.
        default_lang: str = app.config.get("BABEL_DEFAULT_LOCALE", "es_CL")

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

    # Rename the "username" field label to "Teléfono" across all
    # Flask-Security forms before init_app builds the field.
    import flask_security.forms as _fs_forms
    _fs_forms._default_field_labels["username"] = "Teléfono"

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
    )
    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=SecureAdminIndexView())
    init_admin(app, admin)

    # Apply a per-IP rate limit to every Flask-Admin route.  The decorator
    # wraps the check directly into the function body, so registering it as a
    # blueprint before_request handler is enough — Flask-Limiter's automatic
    # endpoint scanning is not required.
    @limiter.limit("120 per hour; 20 per minute")
    def _admin_rate_limit() -> None:
        """Rate-limit guard for the Flask-Admin panel."""

    app.before_request_funcs.setdefault("admin", []).append(_admin_rate_limit)

    @app.context_processor
    def inject_site_languages() -> dict:
        return {"site_languages": _parse_available_langs()}

    @app.context_processor
    def inject_analytics_config() -> dict:
        """Expose analytics keys to all templates as lowercase Jinja globals."""
        return {
            "umami_website_id": app.config.get("UMAMI_WEBSITE_ID", ""),
            "umami_email_pixel_id": app.config.get("UMAMI_EMAIL_PIXEL_ID", ""),
            "gtm_container_id": app.config.get("GTM_CONTAINER_ID", ""),
            "ga_measurement_id": app.config.get("GA_MEASUREMENT_ID", ""),
        }

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


def _init_merchants(app: Flask, admin: Any) -> None:
    providers = []
    if app.config.get("KHIPU_API_KEY", None):
        from merchants.providers.khipu import KhipuProvider

        providers.append(
            KhipuProvider(
                api_key=app.config.get("KHIPU_API_KEY", ""),
                subject="Compra Fonotarot",
                webhook_secret=app.config.get("KHIPU_WEBHOOK_SECRET", ""),
            )
        )
    if app.config.get("FLOW_API_KEY", None):
        from merchants.providers.flow import FlowProvider

        providers.append(
            FlowProvider(
                api_key=app.config.get("FLOW_API_KEY", ""),
                api_secret=app.config.get("FLOW_SECRET_KEY", ""),
            )
        )
    from .models import Order

    merchants_ext.init_app(
        app=app, db=db, models=[Order], providers=providers, admin=admin
    )
    return None


def _register_blueprints(app: Flask) -> None:
    from .account import account_bp
    from .content import blog_bp, content_bp
    from .lab import lab_bp
    from .legacy import legacy_bp
    from .tienda import minutos_bp, pagos_bp, productos_bp, suscripciones_bp

    app.register_blueprint(content_bp)
    app.register_blueprint(blog_bp, url_prefix=app.config["BLOG_URL_PREFIX"])
    app.register_blueprint(pagos_bp)
    app.register_blueprint(minutos_bp)
    app.register_blueprint(suscripciones_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(legacy_bp)

    from .cli import lang_cli, seed_pages_cli, seed_promo_cli

    app.cli.add_command(lang_cli)
    app.cli.add_command(seed_pages_cli)
    app.cli.add_command(seed_promo_cli)
