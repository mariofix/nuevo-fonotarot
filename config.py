"""Application configuration loaded from environment variables.

Usage:
    Copy ``file.env`` to ``.env`` and edit the values, then run the app.
    The ``.env`` file is loaded automatically by the app factory.
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration shared across all environments."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    # SQLAlchemy
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "sqlite:///fonotarot.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Flask-Limiter
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # Flask-Security
    SECURITY_PASSWORD_SALT: str = os.environ.get(
        "SECURITY_PASSWORD_SALT", "dev-password-salt-change-me"
    )
    SECURITY_PASSWORD_HASH: str = "bcrypt"

    # Custom login/logout routing
    SECURITY_LOGIN_URL: str = "/ft-login"
    SECURITY_POST_LOGIN_VIEW: str = "/admin"
    SECURITY_POST_LOGOUT_VIEW: str = "/"

    # Flask-Admin locale
    ADMIN_LOCALE: str = os.environ.get("ADMIN_LOCALE", "en_US")

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

    # Redis — used for live agent state (firenze writes, fonotarot reads)
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Blog URL prefix — change via BLOG_URL_PREFIX env var (e.g. "/noticias")
    BLOG_URL_PREFIX: str = os.environ.get("BLOG_URL_PREFIX", "/blog")


class DevelopmentConfig(Config):
    DEBUG: bool = True


class ProductionConfig(Config):
    DEBUG: bool = False


class TestingConfig(Config):
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    WTF_CSRF_ENABLED: bool = False
    SECURITY_WTF_CSRF_ENABLED: bool = False


config: dict = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
