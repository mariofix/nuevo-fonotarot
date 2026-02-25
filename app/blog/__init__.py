"""Blueprint for the public blog."""

from flask import Blueprint

blog_bp = Blueprint("blog", __name__, url_prefix="/blog")

from . import views  # noqa: E402, F401
