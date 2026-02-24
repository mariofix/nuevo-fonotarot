from flask import Blueprint

tienda_bp = Blueprint("tienda", __name__, url_prefix="/tienda")

from . import views  # noqa: E402, F401
