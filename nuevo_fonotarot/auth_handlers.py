"""Custom authentication handlers for passwordless signin with remember-me feature."""

import json
from datetime import datetime, timedelta

from flask import current_app
from flask_security.signals import user_authenticated, user_registered


def register_auth_handlers(app):
    """Register Flask-Security signal handlers and middleware for authentication."""

    @user_authenticated.connect_via(app)
    def _on_user_authenticated(sender, user, authn_fresh=True, **extra):
        """Set trusted_until when user checks remember checkbox.

        The authn_fresh parameter indicates if this was a fresh authentication
        (vs. a token/session resumption). We only update trusted_until for
        fresh authentications when remember is set.
        """
        from flask import request

        from .extensions import db

        if not authn_fresh:
            return

        # Check if remember was submitted in the form
        # Flask-Security sends it as a checkbox value (on/off)
        remember = request.form.get("remember") in ("y", "true", "on")

        if remember:
            # Set trust window to 31 days from now
            days = int(current_app.config.get("SECURITY_REMEMBER_ME_DAYS", 31))
            user.trusted_until = datetime.now() + timedelta(days=days)
            db.session.commit()
            current_app.logger.debug(
                "Set trusted_until for user=%s until %s",
                user.id,
                user.trusted_until,
            )

    @user_registered.connect_via(app)
    def _on_user_registered(sender, user, confirm_token, confirmation_token, **kwargs):
        """Initialize email unified-signin for newly registered users."""

        ensure_user_email_signin(user)


def ensure_user_email_signin(user) -> bool:
    """Ensure a user has email signin enabled (TOTP secrets initialized)."""
    from flask import current_app

    from .extensions import db, security

    if isinstance(user.us_totp_secrets, str):
        if user.us_totp_secrets:
            try:
                secrets = json.loads(user.us_totp_secrets)
            except json.JSONDecodeError:
                current_app.logger.warning(
                    "Invalid us_totp_secrets JSON for user=%s; re-initializing email signin",
                    user.id,
                )
                secrets = {}
        else:
            secrets = {}
    else:
        secrets = user.us_totp_secrets or {}

    if "email" not in secrets:
        # Generate a proper TOTP secret using Flask-Security's factory.
        totp_factory = security.totp_factory
        secrets["email"] = totp_factory.generate_totp_secret()
        user.us_totp_secrets = json.dumps(secrets)
        db.session.commit()
        current_app.logger.debug("Initialized email signin for user=%s", user.id)
        return True

    return False
