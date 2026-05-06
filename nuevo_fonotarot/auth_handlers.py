"""Custom authentication handlers for passwordless signin with remember-me feature."""

from datetime import datetime, timedelta, timezone
import json
from flask import current_app
from flask_security import user_authenticated


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
            user.trusted_until = datetime.now(timezone.utc) + timedelta(days=days)
            db.session.commit()
            current_app.logger.debug(
                "Set trusted_until for user=%s until %s",
                user.id,
                user.trusted_until,
            )
    
    # Hook into form submission to ensure user has email signin setup
    from flask_security.signals import us_profile_changed
    
    @us_profile_changed.connect_via(app)
    def _on_us_profile_changed(sender, user, extra_data, **kwargs):
        """Ensure user has email method set up for passwordless signin."""
        from .extensions import db
        
        ensure_user_email_signin(user)


def ensure_user_email_signin(user):
    """Ensure a user has email signin enabled (TOTP secrets initialized)."""
    from flask import current_app
    from .extensions import db, security
    
    if not user.us_totp_secrets:
        # Generate a proper TOTP secret using Flask-Security's factory
        totp_factory = security._totp_factory
        totp_secret = totp_factory.generate_totp_secret()
        
        secrets = {"email": totp_secret}
        user.us_totp_secrets = json.dumps(secrets)
        db.session.commit()
        current_app.logger.debug(
            "Initialized email signin for user=%s", user.id
        )


