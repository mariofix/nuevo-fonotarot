"""Blueprint for user account profile and settings."""

from flask import Blueprint

from ..log import get_logger

logger = get_logger(__name__)

account_bp = Blueprint("account", __name__, url_prefix="/account")
logger.debug("account_bp: blueprint created with url_prefix=%r", account_bp.url_prefix)

from . import views  # noqa: E402, F401
