"""Flask application factory."""

import os

from flask import Flask, request

from flask_security.datastore import SQLAlchemyUserDatastore

from config import config
from app.admin import SecureAdminIndexView, init_admin
from app.extensions import admin, babel, db, limiter, migrate, security, theme


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
            ["en_US", "es_CL", "pt_BR"],
            default=app.config.get("ADMIN_LOCALE", "en_US"),
        )

    babel.init_app(app, locale_selector=_locale_selector)

    # Flask-Security: set up user datastore and initialise extension.
    from app.models import Role, User

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security.init_app(app, user_datastore)

    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=SecureAdminIndexView())

    init_admin(app, admin)


def _register_blueprints(app: Flask) -> None:
    from app.pages import pages_bp

    app.register_blueprint(pages_bp)
