from flask import Blueprint

from ...log import get_logger

logger = get_logger(__name__)

pagos_bp = Blueprint("pagos", __name__, url_prefix="/tienda")
logger.debug("pagos_bp: blueprint created with url_prefix=%r", pagos_bp.url_prefix)

from . import views  # noqa: E402, F401
