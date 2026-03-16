"""Views for the account settings blueprint."""

from flask import current_app, redirect, render_template, request, session, url_for
from flask_security import current_user

from . import account_bp
from ..log import get_logger

logger = get_logger(__name__)


@account_bp.route("/")
def settings():
    """User account settings overview."""
    return render_template("account/settings.html", user=current_user)


@account_bp.route("/set-language/<lang>")
def set_language(lang: str):
    """Persist the chosen locale in the session and redirect back."""
    active = [
        item[1]
        for item in current_app.config.get("AVAILABLE_LANGUAGES", [])
    ]

    if lang in active:
        session["lang"] = lang
        logger.debug("Language set to %r for session", lang)
    else:
        logger.warning("Requested language %r is not in active list %s; ignoring", lang, active)

    next_url = request.referrer or url_for("content.index")
    return redirect(next_url)


@account_bp.route("/set-region/<code>")
def set_region(code: str):
    """Persist the chosen region code in the session and redirect back."""
    active = [item[0] for item in current_app.config.get("REGIONS", [])]

    if code in active:
        session["region"] = code
        logger.debug("Region set to %r for session", code)
    else:
        logger.warning("Requested region %r is not in active list %s; ignoring", code, active)

    next_url = request.referrer or url_for("content.index")
    return redirect(next_url)
