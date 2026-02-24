"""Flask application factory."""

import os

from flask import Flask, request
from flask_admin_tabler import TablerTheme

from config import config
from app.admin import AuthAdminIndexView, init_admin
from app.extensions import admin, babel, db, limiter, migrate


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

    # Flask-Babel: select locale from Accept-Language header, falling back to
    # the configured ADMIN_LOCALE value.
    def _locale_selector():
        return request.accept_languages.best_match(
            ["en", "es", "fr", "de", "pt", "zh_Hans_CN"],
            default=app.config.get("ADMIN_LOCALE", "en"),
        )

    babel.init_app(app, locale_selector=_locale_selector)

    # Apply Tabler theme before creating the Admin instance.
    theme = TablerTheme()
    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=AuthAdminIndexView())

    init_admin(app, admin)


def _register_blueprints(app: Flask) -> None:
    pass
