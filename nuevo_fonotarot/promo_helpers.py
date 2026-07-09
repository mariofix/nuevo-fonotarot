from typing import Any
from flask import current_app, session, url_for, render_template
from .log import get_logger
from .extensions import db, user_datastore
from .firenze import complete_promo_credit, search_client, update_client_profile
from .models import SiteSettings, Role
from flask_security.utils import login_user
from .actions import process_user_registration, register_checkout_account

# SiteSettings key that tracks how many free-trial promos are left.
_PROMO_REMAINING_KEY = "promo_free_minutes_remaining"
_PROMO_INITIAL_STOCK = 36
_PROMO_DURATION_SECONDS = 300  # 5 minutes of free trial credit

logger = get_logger(__name__)


def _promo_claim_remaining() -> tuple[bool, int]:
    """Atomically decrement the promo stock counter.

    Creates the row with the initial stock value when it does not exist yet.
    Returns ``(decremented, new_remaining)``.  ``decremented`` is *False* when
    the stock was already at 0 (promo exhausted).
    """
    # Ensure the row exists before locking it.
    if not SiteSettings.query.filter_by(key=_PROMO_REMAINING_KEY).count():
        row = SiteSettings(
            key=_PROMO_REMAINING_KEY,
            value=str(_PROMO_INITIAL_STOCK),
            module="promo",
            description="Número de canjes de 5 minutos gratuitos disponibles",
        )
        db.session.add(row)
        try:
            db.session.flush()
        except Exception:
            # Another request created the row concurrently — safe to ignore.
            db.session.rollback()

    setting = SiteSettings.query.filter_by(key=_PROMO_REMAINING_KEY).with_for_update().first()
    current = int(setting.value or 0) if setting else 0
    if current <= 0:
        return False, 0
    setting.value = str(current - 1)
    # Caller must commit after a successful Firenze call.
    return True, current - 1


def _send_admin_promo_notification(ani: str, remaining: int, client_id: int) -> None:
    """E-mail every active admin user when a free trial is redeemed."""
    from datetime import datetime

    from daleks.contrib.client import DaleksClient

    admin_role = Role.query.filter_by(name="admin").first()
    if not admin_role:
        return
    recipients = [u.email for u in admin_role.users.all() if u.active and u.email]
    if not recipients:
        return

    redeemed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    daleks_url = current_app.config["DALEKS_URL"]
    daleks_smtp_account = current_app.config["DALEKS_SMTP_ACCOUNT"]
    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")

    try:
        html_body = render_template(
            "email/promo_admin.html",
            masked_ani=ani,
            client_id=client_id,
            remaining=remaining,
            redeemed_at=redeemed_at,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            for recipient in recipients:
                client.send_email(
                    from_address=from_address,
                    to=[recipient],
                    subject=f"[Fonotarot] Nueva promoción de 5 minutos canjeada - client_id: {client_id}",
                    html_body=html_body,
                    smtp_account=daleks_smtp_account,
                )
    except Exception:
        logger.exception("Failed to send admin promo notification email")


def _send_user_promo_instructions(email: str, remaining: int) -> bool:
    """E-mail usage instructions to the user who just redeemed a free trial."""
    from daleks.contrib.client import DaleksClient

    daleks_url = current_app.config["DALEKS_URL"]
    daleks_timeout = current_app.config.get("DALEKS_TIMEOUT", 10)
    from_address = current_app.config.get("SECURITY_EMAIL_SENDER", "hola@fonotarot.cl")
    daleks_smtp_account = current_app.config["DALEKS_SMTP_ACCOUNT"]
    subject_prefix = current_app.config.get("EMAIL_PREFIX", "Tienda")

    try:
        html_body = render_template(
            "email/promo_user.html",
            remaining=remaining,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            client.send_email(
                from_address=from_address,
                to=[email],
                subject=f"[{subject_prefix}] ¡Tus 5 minutos gratuitos en están listos!",
                html_body=html_body,
                smtp_account=daleks_smtp_account,
            )
        return True
    except Exception:
        logger.exception("Failed to send user promo instructions email")
        return False


def _complete_promo_claim(ani: str) -> tuple[dict[str, Any], int]:
    """Complete the promo credit in Firenze for the supplied ANI."""
    client_id = complete_promo_credit(ani, _PROMO_DURATION_SECONDS)
    if client_id is None:
        return {
            "error": "api_error",
            "message": "No se pudo activar la promoción. Inténtalo más tarde.",
        }, 503

    return {
        "success": True,
        "client_id": int(client_id),
        "created": True,
    }, 200


def _finalize_promo_email(email: str) -> tuple[dict[str, Any], int]:
    """Create the local account, sync the Firenze email, and log the user in."""
    ani = session.get("promo_ani")
    client_id = session.get("promo_client_id")
    if not ani or client_id is None:
        return {
            "error": "session_expired",
            "message": "Sesión expirada. Recarga la página.",
        }, 401

    normalized_email = email.strip().lower()
    if session.get("promo_completed") and session.get("promo_email") == normalized_email:
        return {
            "success": True,
            "created": False,
            "client_id": int(client_id),
            "authenticated": True,
            "email_sent": True,
            "redirect": url_for("account.profile"),
        }, 200

    try:
        user, created = register_checkout_account(normalized_email, ani)
    except ValueError:
        return {
            "error": "invalid_data",
            "message": "No pudimos crear tu cuenta. Verifica tu correo e inténtalo otra vez.",
        }, 400
    except Exception:
        logger.exception("promo email finalize: failed to create account for ani=%s", ani)
        return {
            "error": "api_error",
            "message": "No se pudo crear tu cuenta. Inténtalo más tarde.",
        }, 503

    process_user_registration(user)
    if user.firenze_client_id is None:
        user.firenze_client_id = int(client_id)
        if user_datastore is not None:
            clientes_role = user_datastore.find_role("clientes")
            if clientes_role and clientes_role not in user.roles:
                user_datastore.add_role_to_user(user, clientes_role)
        db.session.commit()

    if not update_client_profile(int(user.firenze_client_id), email=normalized_email):
        return {
            "error": "api_error",
            "message": "No se pudo actualizar tu correo en Firenze. Inténtalo más tarde.",
        }, 503

    login_user(user, remember=False, authn_via=["promo"])

    remaining = session.get("promo_remaining", 0)
    session["promo_email"] = normalized_email
    session["promo_completed"] = True

    email_sent = _send_user_promo_instructions(normalized_email, remaining)

    return {
        "success": True,
        "created": created,
        "client_id": int(user.firenze_client_id),
        "authenticated": True,
        "email_sent": email_sent,
        "redirect": url_for("account.profile"),
    }, 200
