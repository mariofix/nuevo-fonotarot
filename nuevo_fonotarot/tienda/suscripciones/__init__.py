from flask import Blueprint

from ...log import get_logger

logger = get_logger(__name__)

suscripciones_bp = Blueprint("suscripciones", __name__, url_prefix="/tienda/suscripciones")
logger.debug("suscripciones_bp: blueprint created with url_prefix=%r", suscripciones_bp.url_prefix)

from . import views  # noqa: E402, F401
