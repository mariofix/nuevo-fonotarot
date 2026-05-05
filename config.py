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
    logger = get_logger(__name__)          # module-scoped (recommended)
    logger = get_logger()                  # root 'nuevo_fonotarot' logger
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

import os

from dotenv import load_dotenv

load_dotenv()


def _make_logging_config(log_level: str = "DEBUG") -> dict:
    """Build a Django-style ``dictConfig`` logging configuration.

    Args:
        log_level: Level string applied to the ``nuevo_fonotarot`` root
                   logger.  The stdlib root logger stays at ``WARNING``
                   to suppress noise from third-party libraries.

    Returns:
        A dict suitable for :func:`logging.config.dictConfig`.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
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
        },
        "loggers": {
            # Root application logger — all nuevo_fonotarot.* loggers inherit
            # from this unless they are explicitly configured below.
            "nuevo_fonotarot": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
        },
        # Keep third-party / stdlib root at WARNING to avoid noise.
        "root": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    }


class Config:
    """Base configuration shared across all environments."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    TRUSTED_HOSTS: list = ["nuevo.fonotarot.com", "tardis.local"]
    DEFAULT_CURRENCY: str = os.environ.get("DEFAULT_CURRENCY", "CLP")
    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str = os.environ.get("DATABASE_URL", "sqlite:///fonotarot.db")
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_RECORD_QUERIES: bool = True
    # Flask-Limiter
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Flask-Security
    SECURITY_PASSWORD_SALT: str = os.environ.get("SECURITY_PASSWORD_SALT", "dev-password-salt-change-me")
    SECURITY_PASSWORD_HASH: str = "bcrypt"

    # Username support: the username field stores an E.164 phone number
    # (digits only, no leading +).  Users can register/login with phone OR
    # email.  PhoneUsernameUtil enforces the format at validation time.
    SECURITY_USERNAME_ENABLE: bool = True
    SECURITY_USERNAME_MIN_LENGTH: int = 10
    SECURITY_USERNAME_MAX_LENGTH: int = 13
    SECURITY_ANONYMOUS_USER_DISABLED: bool = True

    # Custom login/logout routing
    SECURITY_CONFIRMABLE: bool = True
    SECURITY_REGISTERABLE: bool = True
    SECURITY_RECOVERABLE: bool = True
    SECURITY_LOGIN_URL: str = "/ft-login"
    SECURITY_REGISTER_URL: str = "/ft-register"
    SECURITY_RESET_URL: str = "/ft-reset"
    SECURITY_VERIFY_URL: str = "/ft-verify"
    SECURITY_CONFIRM_URL: str = "/ft-confirm"
    SECURITY_POST_LOGIN_VIEW: str = "/ft-admin"
    SECURITY_POST_LOGOUT_VIEW: str = "/"

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
    AVAILABLE_LANGUAGES: list = [
        ["es", "es_CL", "Chile"],
        ["es", "es_US", "EEUU"],
    ]

    # merchants
    MERCHANTS_WEBHOOK_BASE_URL: str = os.environ.get("MERCHANTS_WEBHOOK_BASE_URL", "")
    # Flow payment gateway
    FLOW_API_KEY: str = os.environ.get("FLOW_API_KEY", "")
    FLOW_SECRET_KEY: str = os.environ.get("FLOW_SECRET_KEY", "")
    FLOW_API_URL: str = os.environ.get("FLOW_API_URL", "https://sandbox.flow.cl/api")

    # Khipu payment gateway
    KHIPU_API_KEY: str = os.environ.get("KHIPU_API_KEY", "")
    KHIPU_WEBHOOK_SECRET: str = os.environ.get("KHIPU_WEBHOOK_SECRET", "")

    # Email (Daleks)
    DALEKS_URL: str = os.environ.get("DALEKS_URL", "http://localhost:2525")
    DALEKS_TIMEOUT: int = int(os.environ.get("DALEKS_TIMEOUT", "5"))
    DALEKS_SMTP_ACCOUNT: str | None = os.environ.get("DALEKS_SMTP_ACCOUNT", "fonotarot-cl")
    SECURITY_EMAIL_SENDER: str = os.environ.get("MAIL_DEFAULT_SENDER", f"hola@fonotarot.cl")

    # Blog URL prefix — change via BLOG_URL_PREFIX env var (e.g. "/noticias")
    BLOG_URL_PREFIX: str = os.environ.get("BLOG_URL_PREFIX", "/blog")

    LEGACY_PORTAL_DB_URL: str = ""
    LEGACY_AUDIOTEX_DB_URL: str = ""
    LEGACY_FIRENZE_DB_URL: str = ""

    # Firenze API (external telephony platform for promotions)
    # Firenze client lookup/creation service (internal, not internet-accessible)
    # http://zvn-lin3.local:9002/api/v1/public/ejecutivos
    FIRENZE_API_URL: str = os.environ.get("FIRENZE_API_URL", "http://firenze.local")
    FIRENZE_API_USER: str = os.environ.get("FIRENZE_API_USER", "")
    FIRENZE_API_PASSWORD: str = os.environ.get("FIRENZE_API_PASSWORD", "")
    FIRENZE_API_SCOPES: str = os.environ.get("FIRENZE_API_SCOPES", "")
    FIRENZE_API_TIMEOUT: int = int(os.environ.get("FIRENZE_API_TIMEOUT", "5"))

    DEBUG_TB_ENABLED: bool = False
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


class DevelopmentConfig(Config):
    DEBUG: bool = True
    # Development: default to DEBUG; override with LOG_LEVEL env var.
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    LOGGING: dict = _make_logging_config(os.environ.get("LOG_LEVEL", "DEBUG"))


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
