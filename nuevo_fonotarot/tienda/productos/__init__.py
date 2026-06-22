from flask import Blueprint

from ...log import get_logger

logger = get_logger(__name__)

productos_bp = Blueprint("productos", __name__, url_prefix="/productos")
logger.debug("productos_bp: blueprint created with url_prefix=%r", productos_bp.url_prefix)

from . import views  # noqa: E402, F401
