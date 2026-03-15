from flask import Blueprint

minutos_bp = Blueprint("minutos", __name__, url_prefix="/tienda/minutos")

from . import views  # noqa: E402, F401
