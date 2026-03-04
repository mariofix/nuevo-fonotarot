"""Blueprint for design experiments and home page prototypes."""

from flask import Blueprint

lab_bp = Blueprint("lab", __name__, url_prefix="/lab")

from . import views  # noqa: E402, F401
