"""Blueprint for serving database-backed static HTML pages."""

from flask import Blueprint

pages_bp = Blueprint("pages", __name__)

from . import views  # noqa: E402, F401
