from flask import Blueprint

pagos_bp = Blueprint("pagos", __name__, url_prefix="/tienda")

from . import views  # noqa: E402, F401
