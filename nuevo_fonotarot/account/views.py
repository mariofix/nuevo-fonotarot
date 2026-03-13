"""Views for the account settings blueprint."""

import json
import logging

from flask import redirect, render_template, request, session, url_for
from flask_security import current_user

from . import account_bp
from ..models import SiteSettings

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)


@account_bp.route("/")
def settings():
    """User account settings overview."""
    return render_template("account/settings.html", user=current_user)


@account_bp.route("/set-language/<lang>")
def set_language(lang: str):
    """Persist the chosen locale in the session and redirect back."""
    try:
        raw = SiteSettings.get("available_lang")
        active = (
            [item[1] for item in json.loads(raw)]
            if raw
            else ["es_CL", "en_US", "pt_BR"]
        )
    except Exception:
        active = ["es_CL", "en_US", "pt_BR"]

    if lang in active:
        session["lang"] = lang
        logger.debug("Language set to %r for session", lang)
    else:
        logger.warning("Requested language %r is not in active list %s; ignoring", lang, active)

    next_url = request.referrer or url_for("content.index")
    return redirect(next_url)
