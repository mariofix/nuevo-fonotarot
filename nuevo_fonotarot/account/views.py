"""Views for the account settings blueprint."""

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_security import current_user

from . import account_bp
from ..decorators import login_required_modal
from ..extensions import db
from ..log import get_logger

logger = get_logger(__name__)


@account_bp.route("/", methods=["GET", "POST"])
@login_required_modal
def settings():
    """User account settings and profile management."""
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip() or None
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.rut = request.form.get("rut", "").strip() or None
        current_user.address = request.form.get("address", "").strip() or None
        current_user.commune = request.form.get("commune", "").strip() or None
        current_user.postal_code = request.form.get("postal_code", "").strip() or None
        pref = request.form.get("preferred_payment", "").strip()
        current_user.preferred_payment = pref if pref in ("flow", "khipu") else None
        db.session.commit()
        logger.info("Profile updated for user=%s", current_user.id)
        flash("Perfil actualizado correctamente.", "success")
        return redirect(url_for("account.settings"))

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

    return redirect(url_for("content.index"))

