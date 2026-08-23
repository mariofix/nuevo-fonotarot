## Implementar:
## - whenever
## - pint
## - pydantic-settings
## - complexiply
## - NiceUI (en daleks)

"""Flask application factory."""

import logging.config
import os
from types import SimpleNamespace
from typing import Any

import sentry_sdk
from flask import Flask, g, request, session
from flask_babel import get_locale
from flask_merchants.signals import webhook_event_finished
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config

from .admin import SecureAdminIndexView, init_admin
from .extensions import (
    admin,
    babel,
    cors,
    csrf,
    db,
    limiter,
    merchants_ext,
    migrate,
    security,
    toolbar,
)
from .utils import _LangEntry


def _reset_admin_for_factory_reuse() -> None:
    """Reset Flask-Admin singleton state before binding a new app.

    The ``admin`` extension is a module-level singleton. When multiple app
    instances are created in the same process (for example, during tests),
    previously added model views remain in ``admin._views`` and are
    re-registered on the next app, causing duplicate blueprint names.
    """
    admin.app = None
    # Preserve index view slot so ``Admin.init_app`` doesn't add + register it
    # twice in the same call path.
    admin._views = admin._views[:1]  # type: ignore[attr-defined]
    admin._menu = admin._menu[:1]  # type: ignore[attr-defined]
    admin._menu_categories = {}  # type: ignore[attr-defined]
    admin._menu_links = []  # type: ignore[attr-defined]


def create_flask(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        config_name: One of ``development``, ``production``, or ``testing``.
                     Defaults to the ``FLASK_ENV`` environment variable, or
                     ``development`` when not set.
    """
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    if os.environ.get("SENTRY_DSN", False):
        sentry_sdk.init(
            dsn=os.environ.get("SENTRY_DSN"),
            send_default_pii=True,
            enable_logs=False,
            traces_sample_rate=0.1,
            profile_session_sample_rate=0.1,
            profile_lifecycle="trace",
        )

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Apply Django-style logging configuration from the LOGGING config key.
    # All nuevo_fonotarot.* loggers inherit from the 'nuevo_fonotarot' root
    # logger defined in the LOGGING dict.  Override verbosity with LOG_LEVEL.
    logging.config.dictConfig(app.config["LOGGING"])

    merchant_key = app.config.get("MERCHANTS_KEY")
    if app.config.get("MERCHANTS_EXTERNAL_ENDPOINTS") and (
        not merchant_key or merchant_key in {"dev-merchants-key-change-me", "change-me-to-a-shared-random-secret"}
    ):
        app.logger.warning(
            "MERCHANTS_EXTERNAL_ENDPOINTS is configured but MERCHANTS_KEY is missing or still set to the default placeholder; "
            "remote merchant federation is disabled for this runtime."
        )
        app.config["MERCHANTS_EXTERNAL_ENDPOINTS"] = []

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
    cors.init_app(app)

    # Initialize Flask-Security models before importing User/Role
    from flask_security.models import fsqla_v3 as fsqla

    fsqla.FsModels.set_db_info(db, user_table_name="users", role_table_name="roles")
    limiter.init_app(app)
    toolbar.init_app(app)
    available_langs: list = app.config.get("AVAILABLE_LANGUAGES", [["es", "es_CL", "Español"]])

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

    # Rename the "username" field label to "Teléfono" across all
    # Flask-Security forms before init_app builds the field.
    import flask_security.forms as _fs_forms

    import nuevo_fonotarot.extensions as _ext

    from .models import Role, User

    _fs_forms._default_field_labels["username"] = "Teléfono"

    _ext.user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security.init_app(app, _ext.user_datastore)

    # Register custom authentication handlers and user lifecycle hooks.
    from .auth_handlers import register_auth_handlers

    register_auth_handlers(app)

    # After a new user registers, look them up in Firenze and persist client_id.
    from flask_security.signals import user_registered as _user_registered_signal

    @_user_registered_signal.connect_via(app)
    def _on_user_registered(sender, user, confirm_token, confirmation_token, **extra):
        """Execute post-registration steps for the new user."""
        from .actions import process_user_registration

        try:
            process_user_registration(user)
        except Exception:
            app.logger.exception("_on_user_registered: failed to process user=%s", user.id)

    if app.config.get("TESTING") and admin.app is not None and admin.app is not app:
        _reset_admin_for_factory_reuse()

    admin.init_app(app, index_view=SecureAdminIndexView(url="/ft-admin", menu_icon_type="ti", menu_icon_value="home"))
    init_admin(app, admin)

    @app.before_request
    def _inject_site_settings():
        if app.static_url_path and request.path.startswith(app.static_url_path):
            return
        from .models import SiteSettings

        try:
            all_settings = SiteSettings.all()
            app.logger.debug(f"_inject_site_settings: found {len(all_settings)} SiteSettings")
            all_settings = {f"FT_{k.upper()}": v for k, v in all_settings.items()}
            app.config.from_mapping(all_settings)
        except Exception:
            app.logger.warning("_inject_site_settings: failed to fetch SiteSettings")

    @app.context_processor
    def inject_site_languages() -> dict:
        return {"site_languages": _parse_available_langs()}

    @app.context_processor
    def inject_firenze_public_urls() -> dict[str, str]:
        api_url = app.config.get("FIRENZE_API_URL", "").rstrip("/")
        return {
            "firenze_ejecutivos_url": f"{api_url}/api/v1/public/ejecutivos" if api_url else "",
        }

    @app.context_processor
    def inject_site_settings() -> dict:
        # TO DEPRECATE AFTER CHANGING ACCESS FROM TEMPLATES
        """Expose SEO, analytics, and theme settings to all templates.

        Fetches every needed key in a **single** DB query via
        ``SiteSettings.bulk_get`` so that runtime changes in the admin
        panel are reflected immediately without a restart.
        """
        from datetime import datetime

        from .models import SiteSettings

        theme_keys = ["dark_hours_start", "dark_hours_end"]

        all_keys = theme_keys
        defaults = {"dark_hours_start": "20", "dark_hours_end": "8"}

        try:
            settings = SiteSettings.bulk_get(all_keys, defaults=defaults)
        except Exception:
            from .log import get_logger

            get_logger(__name__).exception(
                "inject_site_settings: failed to fetch SiteSettings — "
                "analytics/SEO values will be empty for this request"
            )
            settings = {key: defaults.get(key, "") for key in all_keys}

        # Build template context — SEO & analytics keys as-is (empty string fallback)
        ctx: dict[str, str] = {}

        # Theme: derive from dark_hours_start / dark_hours_end
        try:
            start = int(settings.get("dark_hours_start") or "20")
            end = int(settings.get("dark_hours_end") or "8")
        except (ValueError, TypeError):
            start, end = 20, 8

        hour = datetime.now().hour
        if start < end:
            is_dark = start <= hour < end
        else:
            is_dark = hour >= start or hour < end

        ctx["default_theme"] = "dark" if is_dark else "light"
        return ctx


def _init_merchants(app: Flask, admin: Any) -> None:
    from .models import Order
    from .signals import _handle_payment_webhook_finished

    merchants_ext.init_app(app=app, db=db, models=[Order], admin=admin)
    webhook_event_finished.connect(
        _handle_payment_webhook_finished,
        sender=app,
        weak=False,
    )
    return None


def _register_blueprints(app: Flask) -> None:
    from .account import account_bp

    # from .lab import lab_bp
    # from .legacy import legacy_bp
    from .api import api_bp, internal_bp
    from .content import blog_bp, content_bp
    from .passwordless import create_passwordless_blueprint
    from .tienda import minutos_bp, pagos_bp, productos_bp, tarjetas_bp  # , suscripciones_bp,

    app.register_blueprint(content_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(blog_bp, url_prefix=app.config["BLOG_URL_PREFIX"])
    app.register_blueprint(pagos_bp)
    app.register_blueprint(minutos_bp)
    # app.register_blueprint(suscripciones_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(tarjetas_bp)
    app.register_blueprint(account_bp, url_prefix="/ft-settings")
    # app.register_blueprint(lab_bp)
    # app.register_blueprint(legacy_bp)
    app.register_blueprint(create_passwordless_blueprint())

    from .cli import lang_cli, legacy_cli, seed_promo_cli, user_cli

    app.cli.add_command(lang_cli)
    app.cli.add_command(seed_promo_cli)
    app.cli.add_command(user_cli)
    app.cli.add_command(legacy_cli)
