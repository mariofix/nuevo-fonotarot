from flask import Blueprint

productos_bp = Blueprint("productos", __name__, url_prefix="/tienda/productos")

from . import views  # noqa: E402, F401
