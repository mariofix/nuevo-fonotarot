"""Flask application factory."""

import logging.config
import os
from typing import Any

from flask import Flask, request, session
from flask_babel import get_locale, _
from flask_security.datastore import SQLAlchemyUserDatastore
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config
from flask_merchants.signals import webhook_event_finished

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
    
    # Initialize Flask-Security models before importing User/Role
    from flask_security.models import fsqla_v3 as fsqla
    fsqla.FsModels.set_db_info(
        db, 
        user_table_name="users", 
        role_table_name="roles"
    )
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
    
    # Hook into Flask-Security to customize the unified signin form
    from flask_security import UnifiedSigninForm
    from .forms import customize_unified_signin_form
    
    # Override the form's __init__ to customize it after creation
    original_init = UnifiedSigninForm.__init__
    def custom_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        customize_unified_signin_form(self)
    UnifiedSigninForm.__init__ = custom_init
    
    # Register custom authentication handlers for remember-me functionality
    from .auth_handlers import register_auth_handlers, ensure_user_email_signin
    register_auth_handlers(app)
    
    # Hook into Flask-Security's lookup_identity to auto-setup email signin
    from flask_security.utils import lookup_identity as _original_lookup_identity
    def _patched_lookup_identity(identity):
        user = _original_lookup_identity(identity)
        if user:
            ensure_user_email_signin(user)
        return user
    
    # Monkey-patch the lookup_identity function
    import flask_security.unified_signin
    flask_security.unified_signin.lookup_identity = _patched_lookup_identity

    # After a new user registers, look them up in Firenze and persist client_id.
    from flask_security.signals import user_registered as _user_registered_signal

    @_user_registered_signal.connect_via(app)
    def _on_user_registered(sender, user, confirm_token, confirmation_token, **extra):
        """Execute post-registration steps for the new user."""
        from .actions import process_user_registration

        try:
            process_user_registration(user)
        except Exception:
            from .log import get_logger as _get_logger
            _get_logger(__name__).exception(
                "_on_user_registered: failed to process user=%s", user.id
            )

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
    admin.init_app(app, index_view=SecureAdminIndexView(url="/ft-admin"))
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
    def inject_firenze_public_urls() -> dict[str, str]:
        api_url = app.config.get("FIRENZE_API_URL", "").rstrip("/")
        return {
            "firenze_ejecutivos_url": f"{api_url}/api/v1/public/ejecutivos" if api_url else "",
        }

    @app.context_processor
    def inject_site_settings() -> dict:
        """Expose SEO, analytics, and theme settings to all templates.

        Fetches every needed key in a **single** DB query via
        ``SiteSettings.bulk_get`` so that runtime changes in the admin
        panel are reflected immediately without a restart.
        """
        from datetime import datetime

        from .admin import _ANALYTICS_KEYS, _SEO_KEYS
        from .models import SiteSettings

        seo_keys = [key for key, *_ in _SEO_KEYS]
        analytics_keys = [key for key, *_ in _ANALYTICS_KEYS]
        theme_keys = ["dark_hours_start", "dark_hours_end"]

        all_keys = seo_keys + analytics_keys + theme_keys
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
        ctx: dict[str, str] = {key: settings.get(key) or "" for key in seo_keys + analytics_keys}

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
    from .tienda.pagos.views import _handle_payment_webhook_finished

    providers = []
    if app.config.get("KHIPU_API_KEY", None):
        from merchants.providers.khipu import KhipuProvider

        providers.append(
            KhipuProvider(
                api_key=app.config.get("KHIPU_API_KEY", ""),
                subject="Compra Fonotarot",
                
            )
        )
    if app.config.get("FLOW_API_KEY", None):
        from merchants.providers.flow import FlowProvider

        providers.append(
            FlowProvider(
                api_key=app.config.get("FLOW_API_KEY", ""),
                api_secret=app.config.get("FLOW_SECRET_KEY", ""),
                api_url=app.config.get("FLOW_API_URL", ""),
            )
        )
    from .models import Order

    merchants_ext.init_app(
        app=app, db=db, models=[Order], providers=providers, admin=admin
    )
    webhook_event_finished.connect(
        _handle_payment_webhook_finished,
        sender=app,
        weak=False,
    )
    return None


def _register_blueprints(app: Flask) -> None:
    from .account import account_bp
    from .content import blog_bp, content_bp
    from .lab import lab_bp
    from .legacy import legacy_bp
    from .passwordless import create_passwordless_blueprint
    from .tienda import minutos_bp, pagos_bp, productos_bp, suscripciones_bp

    app.register_blueprint(content_bp)
    app.register_blueprint(blog_bp, url_prefix=app.config["BLOG_URL_PREFIX"])
    app.register_blueprint(pagos_bp)
    app.register_blueprint(minutos_bp)
    app.register_blueprint(suscripciones_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(account_bp, url_prefix="/ft-settings")
    app.register_blueprint(lab_bp)
    app.register_blueprint(legacy_bp)
    app.register_blueprint(create_passwordless_blueprint())

    from .cli import lang_cli, seed_promo_cli, user_cli

    app.cli.add_command(lang_cli)
    app.cli.add_command(seed_promo_cli)
    app.cli.add_command(user_cli)
