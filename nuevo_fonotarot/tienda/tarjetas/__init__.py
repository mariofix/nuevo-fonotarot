from flask import Blueprint

from ...log import get_logger

logger = get_logger(__name__)

tarjetas_bp = Blueprint("tarjetas", __name__, url_prefix="/tarjetas")
logger.debug("tarjetas_bp: blueprint created with url_prefix=%r", tarjetas_bp.url_prefix)

from . import views  # noqa: E402, F401
