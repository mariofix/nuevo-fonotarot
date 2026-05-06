"""LegacyPHP blueprint — Python port of the old PHP admin reports."""

from flask import Blueprint

from ..log import get_logger

logger = get_logger(__name__)

legacy_bp = Blueprint(
    "legacy",
    __name__,
    url_prefix="/legacy",
    template_folder="../../templates/legacy",
)
logger.debug("legacy_bp: blueprint created with url_prefix=%r", legacy_bp.url_prefix)

from . import views  # noqa: E402, F401  (registers routes)

