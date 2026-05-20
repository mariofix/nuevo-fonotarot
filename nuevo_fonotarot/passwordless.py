"""
Passwordless (two-step) authentication blueprint.

This implements a cleaner UX than Flask-Security's unified signin by splitting
the process into two distinct steps:
1. Request Code: User enters their email in a login modal
2. Verify Code: User enters the 6-digit code they received

This avoids confusing UX where both "Send Code" and "Verify Code" buttons
appear on the same form, and eliminates double-validation errors.

Architecture:
- POST /passwordless/request-code → Send code via chosen method
- POST /passwordless/verify-code → Verify code and authenticate
- Session-based state: Identity and method persisted between requests
"""

from __future__ import annotations

import json
import typing as t
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, session, redirect, flash, url_for
from flask_babel import lazy_gettext as _l
from flask_security.utils import login_user
from wtforms import StringField, HiddenField, PasswordField, BooleanField, SubmitField, validators
from flask_security.forms import Form
from flask_security.utils import config_value as cv

from .extensions import db, security
from .models import User
from .log import get_logger

if t.TYPE_CHECKING:
    from flask.typing import ResponseValue

logger = get_logger(__name__)


def _get_totp_secrets(user: User) -> dict:
    """Get TOTP secrets dictionary for a user (handles JSON parsing)."""
    secrets = user.us_totp_secrets
    if isinstance(secrets, str):
        return json.loads(secrets) if secrets else {}
    return secrets or {}




class RequestCodeForm(Form):
    """Step 1: User enters email to receive the access code."""

    identity = StringField(
        label=_l("Correo electrónico"),
        validators=[
            validators.DataRequired(message=_l("Ingresa tu correo electrónico")),
            validators.Email(message=_l("Ingresa un correo válido")),
        ],
        render_kw={"placeholder": "tu@email.com", "autocomplete": "email"},
    )

    method = HiddenField(default="email")

    submit = SubmitField(_l("Enviar código"))

    def validate(self, **kwargs: t.Any) -> bool:
        if not super().validate(**kwargs):
            return False

        # Look up user by identity
        from flask_security.utils import lookup_identity

        self.user = lookup_identity(self.identity.data)
        if not self.user:
            self.identity.errors.append(_l("Correo no encontrado"))
            return False

        if not self.user.is_active:
            self.identity.errors.append(_l("Cuenta desactivada"))
            return False

        # Check if method is enabled and available for this user
        self.method.data = "email"
        enabled_methods = cv("US_ENABLED_METHODS")
        if self.method.data not in enabled_methods:
            self.method.errors.append(_l("Método no disponible"))
            return False

        # Check if user has set up this method
        totp_secrets = _get_totp_secrets(self.user)

        if self.method.data not in totp_secrets:
            self.method.errors.append(_l("Primero debes configurar el acceso por correo"))
            return False

        return True


class VerifyCodeForm(Form):
    """Step 2: User enters the code they received."""

    passcode = PasswordField(
        label=_l("Código de acceso"),
        validators=[
            validators.DataRequired(message=_l("Ingresa el código que recibiste")),
            validators.Length(min=6, max=6, message=_l("El código debe tener 6 dígitos")),
        ],
        render_kw={
            "placeholder": "000000",
            "autocomplete": "one-time-code",
            "pattern": "[0-9]{6}",
        },
    )

    remember_me = BooleanField(_l("Recuérdame por 31 días"))

    submit = SubmitField(_l("Verificar código"))

    def validate(self, **kwargs: t.Any) -> bool:
        if not super().validate(**kwargs):
            return False

        # Get identity/method from session
        identity = session.get("_pwl_identity")
        method = session.get("_pwl_method")

        if not identity or not method:
            self.form_errors.append(_l("Sesión expirada. Intenta de nuevo."))
            return False

        # Look up user
        from flask_security.utils import lookup_identity

        user = lookup_identity(identity)
        if not user:
            self.form_errors.append(_l("Usuario no encontrado"))
            return False

        if not user.is_active:
            self.form_errors.append(_l("Cuenta desactivada"))
            return False

        self.user = user

        # Verify passcode against stored TOTP secret
        totp_secrets = _get_totp_secrets(user)

        if method not in totp_secrets:
            self.form_errors.append(_l("Método no válido"))
            return False

        # Use Flask-Security's TOTP factory to verify
        if not security.totp_factory.verify_totp(
            token=self.passcode.data,
            totp_secret=totp_secrets[method],
            user=user,
            window=cv("US_TOKEN_VALIDITY"),
        ):
            user.track_failed_authn("passcode")
            db.session.commit()
            self.passcode.errors.append(_l("Código inválido o expirado"))
            return False

        self.authn_via = method
        return True


def create_passwordless_blueprint() -> Blueprint:
    """Create the passwordless authentication blueprint."""

    bp = Blueprint(
        "passwordless",
        __name__,
        url_prefix="/passwordless",
        template_folder="templates",
    )

    @bp.route("/request-code", methods=["GET", "POST"])
    def request_code() -> ResponseValue:
        """
        Step 1: Request a code via email.

        GET: Redirect to a public page and open the modal form
        POST: Process modal form, send code, redirect to verify page
        """
        from urllib.parse import urlencode

        next_url = request.values.get("next")
        safe_next_url = next_url if next_url and next_url.startswith("/") else ""

        def _modal_redirect(identity: str = "") -> ResponseValue:
            target = safe_next_url or "/"
            params: dict[str, str] = {"passwordless": "1"}
            if identity:
                params["identity"] = identity
            if safe_next_url:
                params["next"] = safe_next_url
            separator = "&" if "?" in target else "?"
            return redirect(f"{target}{separator}{urlencode(params)}")

        if request.method == "GET":
            return _modal_redirect()

        form = RequestCodeForm()

        if form.validate_on_submit():
            user = form.user
            method = "email"

            # Get TOTP secret for this method
            totp_secrets = _get_totp_secrets(user)

            # Send code via the chosen method
            msg = user.us_send_security_token(
                method,
                totp_secret=totp_secrets[method],
                phone_number=getattr(user, "us_phone_number", None),
                send_magic_link=True,
            )

            if msg:
                # Error sending code
                form.identity.errors.append(_l("Error enviando el código. Intenta de nuevo."))
                logger.warning(
                    f"Failed to send {method} code to user {user.id}: {msg}"
                )
                for error in form.identity.errors:
                    flash(str(error), "error")
                return _modal_redirect(form.identity.data or "")

            # Success: Store identity/method in session and redirect
            session["_pwl_identity"] = form.identity.data
            session["_pwl_method"] = method
            session["_pwl_timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(
                f"Passwordless code sent via {method} to user {user.id} ({user.email})"
            )

            verify_url = url_for(
                "passwordless.verify_code",
                next=safe_next_url or None,
            )
            return redirect(verify_url)

        for error in form.identity.errors + form.method.errors + form.form_errors:
            flash(str(error), "error")
        return _modal_redirect(form.identity.data or "")

    @bp.route("/verify-code", methods=["GET", "POST"])
    def verify_code() -> ResponseValue:
        """
        Step 2: Verify the code and authenticate.

        GET: Display the verification form
        POST: Verify code, authenticate user, redirect to dashboard
        """
        # Check session state
        identity = session.get("_pwl_identity")
        method = session.get("_pwl_method")
        timestamp = session.get("_pwl_timestamp")

        if not identity or not method or not timestamp:
            # Session expired or tampered with
            return redirect("/passwordless/request-code")

        # Check if code request is stale (e.g., older than 10 minutes)
        try:
            req_time = datetime.fromisoformat(timestamp)
            if datetime.now(timezone.utc) - req_time > timedelta(minutes=10):
                session.pop("_pwl_identity", None)
                session.pop("_pwl_method", None)
                session.pop("_pwl_timestamp", None)
                return redirect("/passwordless/request-code")
        except (ValueError, TypeError):
            return redirect("/passwordless/request-code")

        form = VerifyCodeForm()

        if form.validate_on_submit():
            user = form.user
            remember_me = form.remember_me.data

            # Successful authentication
            # Set trusted_until for remember-me functionality
            if remember_me:
                user.trusted_until = datetime.now(timezone.utc) + timedelta(days=31)
                db.session.commit()

            # Clean session
            session.pop("_pwl_identity", None)
            session.pop("_pwl_method", None)
            session.pop("_pwl_timestamp", None)

            # Log user in with Flask-Security's login_user which supports authn_via
            login_user(user, remember=remember_me, authn_via=[method])
            db.session.commit()

            logger.info(
                f"Passwordless authentication successful for user {user.id} "
                f"({user.email}) via {method}"
            )

            # Redirect to next or dashboard
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)

            return redirect("/")

        from flask import render_template
        return render_template(
            "security/passwordless/verify_code.html",
            form=form,
            method=method,
        )

    return bp
