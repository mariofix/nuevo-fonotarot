"""Blueprint for the public home page."""

from flask import Blueprint

home_bp = Blueprint("home", __name__)

from . import views  # noqa: E402, F401
