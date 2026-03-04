"""Blueprint for user account settings."""

from flask import Blueprint

account_bp = Blueprint("account", __name__, url_prefix="/account")

from . import views  # noqa: E402, F401
