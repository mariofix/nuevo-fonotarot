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

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "sqlite:///fonotarot.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SQLALCHEMY_RECORD_QUERIES: bool = True
    # Flask-Limiter
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Flask-Security
    SECURITY_PASSWORD_SALT: str = os.environ.get(
        "SECURITY_PASSWORD_SALT", "dev-password-salt-change-me"
    )
    SECURITY_PASSWORD_HASH: str = "bcrypt"

    # Custom login/logout routing
    SECURITY_REGISTRABLE: bool = True
    SECURITY_LOGIN_URL: str = "/ft-login"
    SECURITY_POST_LOGIN_VIEW: str = "/admin"
    SECURITY_POST_LOGOUT_VIEW: str = "/"

    # Flask-Admin locale
    ADMIN_LOCALE: str = os.environ.get("ADMIN_LOCALE", "es_CL")

    # Default public-facing locale used when no language is set in the
    # session and Accept-Language negotiation yields no match.
    DEFAULT_LANGUAGE: str = os.environ.get("DEFAULT_LANGUAGE", "es_CL")

    # Flow payment gateway
    FLOW_API_KEY: str = os.environ.get("FLOW_API_KEY", "")
    FLOW_SECRET_KEY: str = os.environ.get("FLOW_SECRET_KEY", "")
    FLOW_API_URL: str = os.environ.get("FLOW_API_URL", "https://sandbox.flow.cl/api")
    FLOW_CONFIRMATION_URL: str = os.environ.get("FLOW_CONFIRMATION_URL", "")

    # Khipu payment gateway
    KHIPU_API_KEY: str = os.environ.get("KHIPU_API_KEY", "")

    # Email (Flask-Mail)
    MAIL_SERVER: str = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT: int = int(os.environ.get("MAIL_PORT", "25"))
    MAIL_USE_TLS: bool = os.environ.get("MAIL_USE_TLS", "false").lower() == "true"
    MAIL_USE_SSL: bool = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME: str | None = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD: str | None = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER: str = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@fonotarot.cl")

    # Blog URL prefix — change via BLOG_URL_PREFIX env var (e.g. "/noticias")
    BLOG_URL_PREFIX: str = os.environ.get("BLOG_URL_PREFIX", "/blog")

    LEGACY_PORTAL_DB_URL: str = ""
    LEGACY_AUDIOTEX_DB_URL: str = ""
    LEGACY_FIRENZE_DB_URL: str = ""

    # Firenze API (external telephony platform for promotions)
    FIRENZE_API_URL: str = os.environ.get("FIRENZE_API_URL", "https://firenze.156.cl")
    FIRENZE_API_USER: str = os.environ.get("FIRENZE_API_USER", "")
    FIRENZE_API_PASSWORD: str = os.environ.get("FIRENZE_API_PASSWORD", "")
    FIRENZE_API_SCOPES: str = os.environ.get("FIRENZE_API_SCOPES", "audiotex")

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
