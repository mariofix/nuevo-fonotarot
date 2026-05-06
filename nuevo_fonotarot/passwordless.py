"""
Passwordless (two-step) authentication blueprint.

This implements a cleaner UX than Flask-Security's unified signin by splitting
the process into two distinct steps:
1. Request Code: User enters identity and selects method (email/authenticator/sms)
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

from flask import Blueprint, request, session, redirect, current_app
from flask_login import current_user, login_user
from wtforms import StringField, RadioField, PasswordField, BooleanField, SubmitField, validators, ValidationError
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
    """Step 1: User enters identity and selects delivery method."""

    identity = StringField(
        label="Email o Identidad",
        validators=[validators.DataRequired(message="Ingresa tu email o identidad")],
        render_kw={"placeholder": "tu@email.com"},
    )

    method = RadioField(
        label="Método de entrega",
        choices=[
            ("email", "Código por email"),
            ("authenticator", "Aplicación autenticadora"),
            ("sms", "Código por SMS"),
        ],
        validators=[validators.DataRequired()],
    )

    submit = SubmitField("Enviar Código")

    def validate(self, **kwargs: t.Any) -> bool:
        if not super().validate(**kwargs):
            return False

        # Look up user by identity
        from flask_security.utils import lookup_identity

        self.user = lookup_identity(self.identity.data)
        if not self.user:
            self.identity.errors.append("Email o identidad no encontrado")
            return False

        if not self.user.is_active:
            self.identity.errors.append("Cuenta desactivada")
            return False

        # Check if method is enabled and available for this user
        enabled_methods = cv("US_ENABLED_METHODS")
        if self.method.data not in enabled_methods:
            self.method.errors.append("Método no disponible")
            return False

        # Check if user has set up this method
        totp_secrets = _get_totp_secrets(self.user)

        if self.method.data not in totp_secrets:
            self.method.errors.append(
                f"Primero debes configurar el método {self.method.data}"
            )
            return False

        # For SMS: verify phone number is set
        if self.method.data == "sms" and not self.user.us_phone_number:
            self.method.errors.append("Primero debes registrar tu número telefónico")
            return False

        return True


class VerifyCodeForm(Form):
    """Step 2: User enters the code they received."""

    passcode = PasswordField(
        label="Código de acceso",
        validators=[
            validators.DataRequired(message="Ingresa el código que recibiste"),
            validators.Length(min=6, max=6, message="El código debe tener 6 dígitos"),
        ],
        render_kw={
            "placeholder": "000000",
            "autocomplete": "one-time-code",
            "pattern": "[0-9]{6}",
        },
    )

    remember_me = BooleanField("Recuérdame por 31 días")

    submit = SubmitField("Verificar Código")

    def validate(self, **kwargs: t.Any) -> bool:
        if not super().validate(**kwargs):
            return False

        # Get identity/method from session
        identity = session.get("_pwl_identity")
        method = session.get("_pwl_method")

        if not identity or not method:
            self.form_errors.append("Sesión expirada. Intenta de nuevo.")
            return False

        # Look up user
        from flask_security.utils import lookup_identity

        user = lookup_identity(identity)
        if not user:
            self.form_errors.append("Usuario no encontrado")
            return False

        if not user.is_active:
            self.form_errors.append("Cuenta desactivada")
            return False

        self.user = user

        # Verify passcode against stored TOTP secret
        totp_secrets = _get_totp_secrets(user)

        if method not in totp_secrets:
            self.form_errors.append("Método no válido")
            return False

        # Use Flask-Security's TOTP factory to verify
        if not security.totp_factory.verify_totp(
            token=self.passcode.data,
            totp_secret=totp_secrets[method],
            user=user,
            window=cv("US_TOKEN_VALIDITY"),
        ):
            user.track_failed_authn("passcode")
            self.passcode.errors.append("Código inválido o expirado")
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
        Step 1: Request a code via email, SMS, or authenticator.

        GET: Display the form
        POST: Process form, send code, redirect to verify page
        """
        form = RequestCodeForm()

        if form.validate_on_submit():
            user = form.user
            method = form.method.data

            # Get TOTP secret for this method
            totp_secrets = _get_totp_secrets(user)

            # Send code via the chosen method
            msg = user.us_send_security_token(
                method,
                totp_secret=totp_secrets[method],
                phone_number=getattr(user, "us_phone_number", None),
                send_magic_link=False,
            )

            if msg:
                # Error sending code
                form.method.errors.append(f"Error enviando código: {msg}")
                logger.warning(
                    f"Failed to send {method} code to user {user.id}: {msg}"
                )
                from flask import render_template
                return render_template(
                    "security/passwordless/request_code.html",
                    form=form,
                )

            # Success: Store identity/method in session and redirect
            session["_pwl_identity"] = form.identity.data
            session["_pwl_method"] = method
            session["_pwl_timestamp"] = datetime.now(timezone.utc).isoformat()

            logger.info(
                f"Passwordless code sent via {method} to user {user.id} ({user.email})"
            )

            return redirect("/passwordless/verify-code")

        from flask import render_template
        return render_template(
            "security/passwordless/request_code.html",
            form=form,
        )

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

            # Log user in
            login_user(user, remember=remember_me, authn_via=[form.authn_via])

            logger.info(
                f"Passwordless authentication successful for user {user.id} "
                f"({user.email}) via {form.authn_via}"
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
