"""LegacyPHP blueprint — Python port of the old PHP admin reports."""

from flask import Blueprint

legacy_bp = Blueprint(
    "legacy",
    __name__,
    url_prefix="/legacy",
    template_folder="../../templates/legacy",
)

from . import views  # noqa: E402, F401  (registers routes)
