from flask import Blueprint

core_bp = Blueprint("core", __name__)

from . import views  # noqa: E402, F401
