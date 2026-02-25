"""Views for the pages blueprint."""

from flask import abort, make_response, render_template

from app.models import StaticPage

from . import pages_bp


@pages_bp.route("/<path:page_path>")
def static_page(page_path: str):
    """Serve a static HTML page stored in the database.

    Supports nested paths such as ``/about-us``, ``/help``,
    ``/level1/level2``, ``/level1/help``.  The path is normalised before
    lookup so that variations in capitalisation or trailing slashes all
    resolve to the same record.
    """
    normalised = StaticPage.normalize_path(page_path)
    page = StaticPage.query.filter_by(path=normalised, is_active=True).first()
    if page is None:
        abort(404)
    response = make_response(render_template("pages/page.html", page=page))
    response.headers["Cache-Control"] = "no-store"
    return response
