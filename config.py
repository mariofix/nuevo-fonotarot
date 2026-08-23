"""Application configuration loaded from environment variables.

Usage:
    Copy ``file.env`` to ``.env`` and edit the values, then run the app.
    The ``.env`` file is loaded automatically by the app factory.

Logging
-------
Logging is configured Django-style via a ``LOGGING`` dictionary on each
config class.  The dict is passed verbatim to :func:`logging.config.dictConfig`
during application startup.

To control verbosity, set the ``LOG_LEVEL`` environment variable
(e.g. ``LOG_LEVEL=INFO``).  Each config class picks a sensible default:
``DEBUG`` for development, ``INFO`` for production.

To use a logger in application code::

    from nuevo_fonotarot.log import get_logger

    logger = get_logger(__name__)  # module-scoped (recommended)
    logger = get_logger()  # root 'nuevo_fonotarot' logger
    logger = get_logger("nuevo_fonotarot.payments")  # any named logger

The ``nuevo_fonotarot`` logger hierarchy is the single entry point
configured in ``LOGGING["loggers"]``.  All child loggers (``__name__``
in submodules) inherit its level and handlers automatically.

Note on FLASK_-prefixed environment variables
---------------------------------------------
``python-dotenv`` loads *all* keys from ``.env`` into ``os.environ``,
including ``FLASK_DEBUG`` and ``FLASK_ENV``.  However, only ``FLASK_ENV``
is explicitly read here (to select the config class).  Other ``FLASK_*``
variables are **not** automatically applied to ``app.config`` because
this project uses ``app.config.from_object()`` rather than Flask's
``app.config.from_prefixed_env("FLASK")``.  This is intentional — the
Config class pattern gives explicit, type-annotated control over every
setting.  If you need ``FLASK_DEBUG`` to toggle debug mode, use the
``DEBUG`` config attribute or set ``LOG_LEVEL`` / ``FLASK_ENV`` instead.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")


def _make_logging_config(log_level: str = "DEBUG") -> dict:
    """Build a Django-style ``dictConfig`` logging configuration.

    Args:
        log_level: Level string applied to the ``nuevo_fonotarot`` root
                   logger.  The stdlib root logger stays at ``WARNING``
                   to suppress noise from third-party libraries.

    Returns:
        A dict suitable for :func:`logging.config.dictConfig`.
    """
    # Ensure logs directory exists
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    log_file = logs_dir / "nuevo-fonotarot.log"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {
                "format": "[%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_file),
                "when": "midnight",
                "interval": 1,
                "backupCount": 3,
                "formatter": "verbose",
            },
        },
        "loggers": {
            # Root application logger — all nuevo_fonotarot.* loggers inherit
            # from this unless they are explicitly configured below.
            "nuevo_fonotarot": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            # Third-party payment SDK logs are emitted outside the
            # nuevo_fonotarot namespace, so they need explicit entries.
            "merchants": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
            "flask_merchants": {
                "handlers": ["console", "file"],
                "level": log_level,
                "propagate": False,
            },
        },
        # Keep third-party / stdlib root at WARNING to avoid noise.
        "root": {
            "handlers": ["console", "file"],
            "level": "WARNING",
        },
    }


class Config:
    """Base configuration shared across all environments."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    TRUSTED_HOSTS: list = ["tienda.fonotarot.com", "localhost", "tardis.local", "zvn-lin4.local", "10.0.0.4"]
    SERVER_NAME: str = os.environ.get("SERVER_NAME", "localhost")
    PREFERRED_URL_SCHEME: str = os.environ.get("PREFERRED_URL_SCHEME", "http")
    DEFAULT_CURRENCY: str = os.environ.get("DEFAULT_CURRENCY", "CLP")
    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("SQLALCHEMY_DATABASE_URI", "sqlite:///fonotarot.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_RECORD_QUERIES: bool = True
    # Flask-Limiter
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Flask-Security
    SECURITY_PASSWORD_SALT: str = os.environ.get("SECURITY_PASSWORD_SALT", "dev-password-salt-change-me")

    # Username support: the username field stores an E.164 phone number
    # (digits only, no leading +).  Users can register/login with phone OR
    # email.  PhoneUsernameUtil enforces the format at validation time.
    SECURITY_USERNAME_ENABLE: bool = True
    SECURITY_USERNAME_MIN_LENGTH: int = 10
    SECURITY_USERNAME_MAX_LENGTH: int = 13
    SECURITY_ANONYMOUS_USER_DISABLED: bool = True

    # Custom login/logout routing
    SECURITY_TRACKABLE: bool = True
    SECURITY_CONFIRMABLE: bool = True
    SECURITY_REGISTERABLE: bool = True
    SECURITY_RECOVERABLE: bool = False
    SECURITY_CHANGEABLE: bool = False
    SECURITY_WEBAUTHN: bool = False
    SECURITY_UNIFIED_SIGNIN: bool = True
    SECURITY_US_ENABLED_METHODS: list = ["email"]  # Email and authenticator app
    SECURITY_US_SIGNIN_REPLACES_LOGIN: bool = False  # Replace /login with /us-signin
    SECURITY_LOGIN_URL: str = "/ft-admin-login"
    SECURITY_REGISTER_URL: str = "/ft-register"
    SECURITY_RESET_URL: str = "/ft-reset"
    SECURITY_CONFIRM_URL: str = "/ft-confirm"
    SECURITY_CHANGE_URL: str = "/ft-settings"
    SECURITY_POST_CONFIRM_VIEW: str = "/passwordless/request-code"
    SECURITY_POST_LOGIN_VIEW: str = "/"
    SECURITY_POST_LOGOUT_VIEW: str = "/"
    SECURITY_EMAIL_SUBJECT_REGISTER: str = "Te damos la bienvenida a Fonotarot"
    SECURITY_EMAIL_SUBJECT_EMAIL_CONFIRMATION: str = "Confirma tu correo para acceder a Fonotarot"
    SECURITY_US_EMAIL_SUBJECT: str = "Esta es tu contraseña para ingresar a Fonotarot"

    # Unified signin settings
    SECURITY_US_EMAIL_VALIDITY: int = 300  # One-time code valid for 5 minutes
    SECURITY_US_TOKEN_VALIDITY: int = 300  # One-time link valid for 5 minutes
    SECURITY_REMEMBER_ME_DAYS: int = 31  # Trust window for remember_me checkbox

    # TOTP settings (required for unified signin)
    SECURITY_TOTP_SECRETS: dict = {"1": os.environ.get("SECURITY_TOTP_SECRET_1", "JBSWY3DPEBLW64TMMQQ")}
    SECURITY_TOTP_ISSUER: str = "Fonotarot"

    # Flask-Admin locale
    ADMIN_LOCALE: str = os.environ.get("ADMIN_LOCALE", "es_CL")

    # Flask-Babel: default locale used when the locale selector returns None
    # and as the deploy-time fallback in _locale_selector().
    # Can be overridden at runtime via SiteSettings key ``default_language``.
    BABEL_DEFAULT_LOCALE: str = os.environ.get("BABEL_DEFAULT_LOCALE", "es_CL")

    # Available languages for the public language switcher.
    # Each entry is a [short_code, locale, label] triple.
    # Managed here (not in SiteSettings) so Flask-Admin Babel and Babel
    # locale negotiation know the list before any DB request is made.
    AVAILABLE_LANGUAGES: list = json.loads(os.environ.get("AVAILABLE_LANGUAGES", '[["es", "es_CL", "Chile"]]'))
    # merchants
    MERCHANTS_KEY: str = os.environ.get("MERCHANTS_KEY", "dev-merchants-key-change-me")
    MERCHANTS_WEBHOOK_BASE_URL: str = os.environ.get("MERCHANTS_WEBHOOK_BASE_URL", "")
    MERCHANTS_AUTOLOAD_PROVIDERS: list = os.environ.get("MERCHANTS_AUTOLOAD_PROVIDERS", "").split(",")
    MERCHANTS_EXTERNAL_ENDPOINTS: list[str] = [
        item.strip() for item in os.environ.get("MERCHANTS_EXTERNAL_ENDPOINTS", "").split(",") if item.strip()
    ]
    FLOW_API_KEY: str = os.environ.get("FLOW_API_KEY", "")
    FLOW_SECRET_KEY: str = os.environ.get("FLOW_SECRET_KEY", "")
    FLOW_API_URL: str = os.environ.get("FLOW_API_URL", "https://sandbox.flow.cl/api")
    KHIPU_API_KEY: str = os.environ.get("KHIPU_API_KEY", "")
    KHIPU_WEBHOOK_SECRET: str = os.environ.get("KHIPU_WEBHOOK_SECRET", "")
    STRIPE_API_KEY: str = os.environ.get("FLOW_API_KEY", "")
    PAYPAL_ACCESS_TOKEN: str = os.environ.get("FLOW_API_KEY", "")

    # Email (Daleks)
    DALEKS_URL: str = os.environ.get("DALEKS_URL", "http://localhost:2525")
    DALEKS_TIMEOUT: int = int(os.environ.get("DALEKS_TIMEOUT", "5"))
    DALEKS_SMTP_ACCOUNT: str | None = os.environ.get("DALEKS_SMTP_ACCOUNT", "")
    SECURITY_EMAIL_SENDER: str = os.environ.get("MAIL_DEFAULT_SENDER", "")

    # Telegram notifications (Watchtower webhook)
    # Format: telegram://BOT_TOKEN@telegram?chats=CHAT_ID&preview=No
    TELEGRAM_WEBHOOK_URL: str = os.environ.get("TELEGRAM_WEBHOOK_URL", "")

    # Blog URL prefix — change via BLOG_URL_PREFIX env var (e.g. "/noticias")
    BLOG_URL_PREFIX: str = os.environ.get("BLOG_URL_PREFIX", "/blog")

    LEGACY_PORTAL_DB_URL: str = ""
    LEGACY_AUDIOTEX_DB_URL: str = ""
    LEGACY_FIRENZE_DB_URL: str = ""

    # Firenze API (external telephony platform for promotions)
    # Firenze client lookup/creation service (internal, not internet-accessible)
    # http://zvn-lin3.local:9002/api/v1/public/ejecutivos
    FIRENZE_API_URL: str = os.environ.get("FIRENZE_API_URL", "")
    FIRENZE_API_URL_LOCAL: str = os.environ.get("FIRENZE_API_URL_LOCAL", "")
    FIRENZE_API_KEY: str = os.environ.get("FIRENZE_API_KEY", "")
    FIRENZE_API_SECRET: str = os.environ.get("FIRENZE_API_SECRET", "")
    # Backward compatibility with previous Firenze credential names.
    FIRENZE_API_USER: str = os.environ.get("FIRENZE_API_USER", "")
    FIRENZE_API_PASSWORD: str = os.environ.get("FIRENZE_API_PASSWORD", "")
    FIRENZE_API_TIMEOUT: int = int(os.environ.get("FIRENZE_API_TIMEOUT", "5"))

    DEBUG_TB_ENABLED: bool = bool(os.environ.get("DEBUG_TB_ENABLED", False))
    DEBUG_TB_PANELS = (
        "flask_debugtoolbar.panels.versions.VersionDebugPanel",
        "flask_debugtoolbar.panels.timer.TimerDebugPanel",
        "flask_debugtoolbar.panels.headers.HeaderDebugPanel",
        "flask_debugtoolbar.panels.request_vars.RequestVarsDebugPanel",
        "flask_debugtoolbar.panels.config_vars.ConfigVarsDebugPanel",
        "flask_debugtoolbar.panels.template.TemplateDebugPanel",
        "flask_debugtoolbar.panels.sqlalchemy.SQLAlchemyDebugPanel",
        "flask_debugtoolbar.panels.logger.LoggingPanel",
        "flask_debugtoolbar.panels.route_list.RouteListDebugPanel",
        "flask_debugtoolbar.panels.profiler.ProfilerDebugPanel",
        "flask_debugtoolbar.panels.g.GDebugPanel",
        "flask_debugtoolbar_extrapanels.SignalsPanel",
    )
    DEBUG_TB_INTERCEPT_REDIRECTS = False

    # ---------------------------------------------------------------------------
    # Logging  (Django-style dictConfig)
    # ---------------------------------------------------------------------------
    # Override LOG_LEVEL via the LOG_LEVEL environment variable.
    # The LOGGING dict is passed to logging.config.dictConfig() at startup.
    # Sub-classes set a different default so dev logs at DEBUG and prod at INFO.
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    LOGGING: dict = _make_logging_config(os.environ.get("LOG_LEVEL", "DEBUG"))
    SESSION_COOKIE_NAME: str = "tienda_fonotarot"

    CORS_ORIGINS = ["https://fonotarot.com", "https://compra.fonotarot.com"]

    SENTRY_DSN = os.environ.get("SENTRY_DSN", None)
    EMAIL_PREFIX = "Tienda Fonotarot"

    # VAPID
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "vapid_private.pem")
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_CLAIMS = {"sub": f"mailto:{os.environ.get('MAIL_DEFAULT_SENDER', 'user@email.com')}"}


class DevelopmentConfig(Config):
    DEBUG: bool = True
    # Development: default to DEBUG; override with LOG_LEVEL env var.
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    LOGGING: dict = _make_logging_config(os.environ.get("LOG_LEVEL", "DEBUG"))
    # Development email configuration: use console backend if no SMTP server configured
    MAIL_DEBUG: bool = True
    # If DALEKS_URL is not set, use Python's debugging backend
    if not os.environ.get("DALEKS_URL"):
        # Use a simple testing backend that just logs emails
        MAIL_SUPPRESS_SEND: bool = False


class ProductionConfig(Config):
    DEBUG: bool = False
    # Production: default to INFO; override with LOG_LEVEL env var.
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOGGING: dict = _make_logging_config(os.environ.get("LOG_LEVEL", "INFO"))


class TestingConfig(Config):
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    WTF_CSRF_ENABLED: bool = False
    SECURITY_WTF_CSRF_ENABLED: bool = False
    # Testing: suppress output unless explicitly requested.
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "WARNING")
    LOGGING: dict = _make_logging_config(os.environ.get("LOG_LEVEL", "WARNING"))


config: dict = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
