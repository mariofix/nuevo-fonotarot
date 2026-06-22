from flask import Blueprint

from ...log import get_logger

logger = get_logger(__name__)

minutos_bp = Blueprint("minutos", __name__, url_prefix="/minutos")
logger.debug("minutos_bp: blueprint created with url_prefix=%r", minutos_bp.url_prefix)

from . import views  # noqa: E402, F401
