import typing
from dataclasses import dataclass

from flask import Blueprint, Flask
from flask_admin.theme import Theme


@dataclass
class TablerTheme(Theme):
    """
    Tabler 1.4.0 theme for Flask-Admin.

    Uses Tabler UI (https://tabler.io/) as the front end, loaded via CDN.

    Templates live in ``flask_admin_tabler/templates/tabler/`` which matches
    ``Theme.folder = "tabler"``.  Registering the package blueprint **before**
    Flask-Admin's admin blueprint ensures our templates are resolved first by
    Flask's template loader.

    Usage::

        from flask_admin_tabler import TablerTheme

        theme = TablerTheme()
        theme.init_app(app)  # call before Admin(app, ...)
        admin = Admin(app, name="my app", theme=theme)

    Or with a custom base template::

        theme = TablerTheme(base_template="my_base.html")
        theme.init_app(app)
        admin = Admin(app, name="my app", theme=theme)
    """

    folder: typing.Literal["tabler"] = "tabler"
    base_template: str = "admin/base.html"
    tabler_icons: bool = True

    # Tabler UI theme settings — map directly to data-bs-* HTML attributes.
    # Defaults match Tabler's own defaults so existing deployments are unaffected.
    theme: str = "light"           # "light" | "dark"
    theme_primary: str = "blue"    # "blue" | "lime" | "azure" | "indigo" | …
    theme_base: str = "gray"       # "gray" | "neutral" | "slate" | "zinc" | "stone"
    theme_font: str = "sans-serif" # "sans-serif" | "serif" | "monospace" | "comic"
    theme_radius: str = "1"        # "0" | "0.5" | "1" | "1.5" | "2"
    inter_font: bool = False       # load Inter font from rsms.me CDN

    def init_app(self, app: Flask) -> None:
        """Register Tabler theme templates and static files with the Flask app.

        Must be called *before* creating the ``Admin`` instance.  Flask
        resolves blueprint templates in registration order, so registering
        this blueprint first guarantees our Tabler templates take priority
        over Flask-Admin's default Bootstrap ones.
        """
        bp = Blueprint(
            "flask_admin_tabler",
            __name__,
            template_folder="templates/tabler",
            static_folder="static",
            static_url_path="/static/flask_admin_tabler",
        )
        app.register_blueprint(bp)
