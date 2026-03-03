from flask import Flask, redirect, session, request
import os
from config import config
from .extensions import db, migrate, limiter, babel, admin, theme, merchants_ext
from .utils import _LangEntry, _FALLBACK_LANGUAGES
import json
from flask_babel import get_locale
from .models import Role, User


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

    def _parse_available_langs() -> list[_LangEntry]:
        """Return language entries from SiteSettings, falling back to defaults."""
        try:
            from .models import SiteSettings

            raw = SiteSettings.get("available_lang")
            if raw:
                return [_LangEntry(*item) for item in json.loads(raw)]
        except Exception:
            pass
        return [_LangEntry(*item) for item in _FALLBACK_LANGUAGES]

    def _active_locales() -> list[str]:
        return [lang.locale for lang in _parse_available_langs()]

    # Flask-Babel: honour explicit session choice first, then Accept-Language,
    # then fall back to DEFAULT_LANGUAGE.
    def _locale_selector() -> str:
        lang = session.get("lang") or request.args.get("lang")
        active = _active_locales()
        if lang:
            if lang in active:
                session["lang"] = lang
                return lang
            # Explicit lang code requested but not available → clear stale
            # session value and show the site in Spanish (primary language).
            session.pop("lang", None)
            return default_lang
        return request.accept_languages.best_match(active, default=default_lang)

    babel.init_app(app, locale_selector=_locale_selector)

    app.jinja_env.globals["get_locale"] = get_locale

    ## Te distrajiste y lo dejaste acá, busca como agregar el user_datastore como extension de flask
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    security.init_app(app, user_datastore)

    theme.init_app(app)

    admin.name = app.config.get("ADMIN_NAME", "Fonotarot Admin")
    admin.theme = theme
    admin.init_app(app, index_view=SecureAdminIndexView())

    # Context processor: inject site_languages into every non-admin template.
    @app.context_processor
    def inject_site_languages() -> dict:
        return {"site_languages": _parse_available_langs()}

    return app
