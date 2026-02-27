from flask import Flask
import os
from .. import config
from .extensions import db, migrate, limiter


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

    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    default_lang: str = app.config.get("DEFAULT_LANGUAGE", "es_CL")

    return app
