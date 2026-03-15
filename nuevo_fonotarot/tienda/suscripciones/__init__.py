from flask import Blueprint

suscripciones_bp = Blueprint("suscripciones", __name__, url_prefix="/tienda/suscripciones")

from . import views  # noqa: E402, F401
