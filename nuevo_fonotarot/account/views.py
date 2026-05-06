"""Views for the account settings blueprint."""

from datetime import datetime, timezone

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from flask_security import current_user, verify_password
from flask_security.changeable import change_user_password
from flask_security.utils import login_user

from . import account_bp
from .forms import ClaimAccountForm
from ..actions import _assign_clientes_role
from ..auth_handlers import ensure_user_email_signin
from ..decorators import login_required_modal
from ..extensions import db
from ..firenze import search_client
from ..log import get_logger
from ..models import User

logger = get_logger(__name__)


@account_bp.route("/", methods=["GET", "POST"])
@login_required_modal
def settings():
    """User account settings and profile management."""
    if request.method == "POST":
        form_type = request.form.get("form_type", "profile")

        if form_type == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            min_length: int = current_app.config.get("SECURITY_PASSWORD_LENGTH_MIN", 8)

            if not verify_password(current_password, current_user.password):
                flash(_("La contraseña actual es incorrecta."), "danger")
            elif len(new_password) < min_length:
                flash(_("La nueva contraseña debe tener al menos %(n)s caracteres.", n=min_length), "danger")
            elif new_password != confirm_password:
                flash(_("Las contraseñas nuevas no coinciden."), "danger")
            else:
                change_user_password(current_user._get_current_object(), new_password)
                logger.info("Password changed for user=%s", current_user.id)
                flash(_("Contraseña actualizada correctamente."), "success")
            return redirect(url_for("account.settings"))

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
    """Persist the chosen locale in the session and redirect back.

    The redirect target is taken from the ``next`` query-string parameter when
    it is a safe same-site relative path (starts with ``/`` but not ``//``).
    Falls back to the site index when ``next`` is absent or unsafe.
    """
    active = [
        item[1]
        for item in current_app.config.get("AVAILABLE_LANGUAGES", [])
    ]

    if lang in active:
        session["lang"] = lang
        logger.debug("Language set to %r for session", lang)
    else:
        logger.warning("Requested language %r is not in active list %s; ignoring", lang, active)

    next_param = request.args.get("next", "").strip()
    if next_param:
        from urllib.parse import urlsplit as _urlsplit
        parsed_next = _urlsplit(next_param)
        # Accept only relative paths (no scheme, no netloc, must start with / but not //)
        if not parsed_next.scheme and not parsed_next.netloc and parsed_next.path.startswith("/") and not parsed_next.path.startswith("//"):
            return redirect(next_param)

    return redirect(url_for("content.index"))


@account_bp.route("/registro/cliente-existente", methods=["GET", "POST"])
def claim_account():
    """Allow captured (telephone) customers to create a web account.

    Verifies the customer's identity against the Firenze telephony platform
    using their email and phone number.  If found, creates a web account with
    the matching ``firenze_client_id`` and ``clientes`` role already assigned,
    then logs the user in immediately.
    """
    if current_user.is_authenticated:
        return redirect(url_for("content.index"))

    form = ClaimAccountForm()

    if form.validate_on_submit():
        email: str = form.email.data.strip().lower()
        phone: str = form.phone.data.strip()

        # Step 1 — verify identity via Firenze
        client_id = search_client(email=email, phone=phone)
        if client_id is None:
            logger.info(
                "claim_account: Firenze lookup found no match for email=%r phone=%r",
                email,
                phone,
            )
            flash(
                _(
                    "No encontramos una cuenta con esos datos en nuestro sistema. "
                    "Verifica tu email y teléfono, o regístrate como cliente nuevo."
                ),
                "danger",
            )
            return render_template("auth/claim_account.html", form=form)

        # Step 2 — check for an existing web account with this email
        existing_user = User.query.filter_by(email=email).first()
        if existing_user is not None:
            logger.info(
                "claim_account: email=%r already has a web account (user=%s)",
                email,
                existing_user.id,
            )
            flash(
                _("Ya tienes una cuenta registrada con ese email. Ingresa aquí."),
                "info",
            )
            return redirect(url_for("security.login"))

        # Step 3 — create the web account
        from ..extensions import user_datastore

        new_user: User = user_datastore.create_user(
            email=email,
            password=form.password.data,
            active=True,
            phone=phone,
            firenze_client_id=client_id,
            confirmed_at=datetime.now(timezone.utc),
        )

        _assign_clientes_role(new_user)

        # Ensure email-based passwordless signin is ready from day one
        ensure_user_email_signin(new_user)

        db.session.commit()

        logger.info(
            "claim_account: created web account for user=%s email=%r "
            "firenze_client_id=%s",
            new_user.id,
            email,
            client_id,
        )

        # Step 4 — log in immediately
        login_user(new_user, authn_via=["claim"])

        flash(_("¡Bienvenida! Tu cuenta ha sido activada correctamente."), "success")
        return redirect(url_for("account.settings"))

    return render_template("auth/claim_account.html", form=form)

