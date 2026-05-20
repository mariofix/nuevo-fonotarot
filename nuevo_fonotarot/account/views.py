"""Views for the account profile and settings blueprint."""

import json

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import _
from flask_security import current_user

from . import account_bp
from ..decorators import login_required_modal
from ..extensions import db
from ..firenze import (
    add_client_ani,
    delete_client_ani,
    list_client_anis,
    search_client_minutes,
    update_client_profile,
)
from ..log import get_logger
from ..models import BlogPost, Order, SiteSettings

logger = get_logger(__name__)

_SETTINGS_TABS = {"profile", "additional-phones", "notifications"}
_NOTIFICATION_OPTIONS = (
    ("purchase", "Notificación de compra"),
    ("tarotista_online", "Notificación de tarotista en línea"),
    ("low_balance", "Notificación de saldo bajo"),
    ("commercial", "Notificación comercial o promocional"),
)


def _load_ejecutivos() -> list[dict[str, str]]:
    """Return tarotista options from SiteSettings."""
    try:
        raw = SiteSettings.get("ejecutivos") or "[]"
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("SiteSettings 'ejecutivos' is not valid JSON")
        return []

    ejecutivos: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        option = str(item.get("option", "")).strip()
        name = str(item.get("name", "")).strip()
        if not option or not name:
            continue
        ejecutivos.append(
            {
                "name": name,
                "avatar": str(item.get("avatar", "")).strip(),
                "option": option,
                "specialty": str(item.get("specialty", "")).strip(),
            }
        )
    return ejecutivos


def _notification_options() -> list[dict[str, str]]:
    """Return translated notification options for the settings form."""
    return [{"key": key, "label": _(label)} for key, label in _NOTIFICATION_OPTIONS]


def _tarotista_by_option(ejecutivos: list[dict[str, str]], option: str | None) -> dict[str, str] | None:
    """Return the matching tarotista row for *option*."""
    if not option:
        return None
    for ejecutivo in ejecutivos:
        if ejecutivo["option"] == option:
            return ejecutivo
    return None


def _settings_tab_from_request(default: str = "profile") -> str:
    """Return the current settings tab from query args."""
    requested = request.args.get("tab", default).strip()
    if requested in _SETTINGS_TABS:
        return requested
    return default


@account_bp.route("/", methods=["GET"])
@account_bp.route("/profile", methods=["GET"])
@login_required_modal
def profile():
    """Read-only profile page with recent activity."""
    ejecutivos = _load_ejecutivos()
    favorite_tarotista = _tarotista_by_option(
        ejecutivos, current_user.favorite_tarotista_option
    )
    notification_options = _notification_options()
    selected_notifications = set(current_user.notification_preferences or [])
    notification_preferences_labels = [
        option["label"]
        for option in notification_options
        if option["key"] in selected_notifications
    ]

    recent_orders = (
        current_user.orders.order_by(Order.created_at.desc()).limit(5).all()
    )
    recent_posts = (
        BlogPost.query.filter_by(published=True)
        .order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "account/profile.html",
        user=current_user,
        recent_orders=recent_orders,
        recent_posts=recent_posts,
        profile_credits_url=url_for("account.profile_credits"),
        subscriptions_enabled=False,
        products_purchased_enabled=False,
        ejecutivos=ejecutivos,
        favorite_tarotista=favorite_tarotista,
        notification_preferences_labels=notification_preferences_labels,
    )


@account_bp.route("/profile/credits", methods=["GET"])
@login_required_modal
def profile_credits():
    """Return the signed-in user's Firenze credit balance in seconds."""
    email = (current_user.email or "").strip().lower()
    client_id = current_user.firenze_client_id
    if client_id is None and not email:
        return jsonify({"ok": True, "found": False, "seconds": 0}), 200

    minutes, error_code = search_client_minutes(client_id=client_id, email=email)
    if error_code is not None:
        logger.warning(
            "profile_credits: Firenze lookup failed for user=%s client_id=%r email=%r error=%s",
            current_user.id,
            client_id,
            email,
            error_code,
        )
        return jsonify({"ok": False, "error": error_code}), 503

    seconds = max(0, int((minutes or 0) * 60))
    return jsonify({"ok": True, "found": minutes is not None, "seconds": seconds}), 200

@account_bp.route("/settings", methods=["GET", "POST"])
@login_required_modal
def settings():
    """User account settings and profile management."""
    active_tab = _settings_tab_from_request()
    ejecutivos = _load_ejecutivos()
    ejecutivos_by_option = {item["option"]: item for item in ejecutivos}
    notification_options = _notification_options()
    notification_option_keys = {item["key"] for item in notification_options}

    if request.method == "POST":
        form_type = request.form.get("form_type", "profile")

        if form_type == "password":
            flash(
                _("El acceso es sin contraseña. La gestión de contraseña está deshabilitada."),
                "info",
            )
            return redirect(url_for("account.settings"))
        if form_type == "add_ani":
            if not current_user.firenze_client_id:
                flash(
                    _("Tu cuenta no tiene un cliente Firenze asociado."),
                    "warning",
                )
                return redirect(url_for("account.settings", tab="additional-phones"))

            candidate_ani = request.form.get("ani", "").strip()
            created_ok, was_created = add_client_ani(
                int(current_user.firenze_client_id),
                candidate_ani,
            )
            if created_ok and was_created:
                flash(_("Teléfono adicional agregado."), "success")
            elif created_ok:
                flash(_("Ese teléfono adicional ya existe."), "info")
            else:
                flash(
                    _("No se pudo agregar el teléfono adicional. Verifica el formato e inténtalo de nuevo."),
                    "danger",
                )
            return redirect(url_for("account.settings", tab="additional-phones"))

        if form_type == "delete_ani":
            if not current_user.firenze_client_id:
                flash(
                    _("Tu cuenta no tiene un cliente Firenze asociado."),
                    "warning",
                )
                return redirect(url_for("account.settings", tab="additional-phones"))

            target_ani = request.form.get("ani", "").strip()
            delete_ok, was_deleted = delete_client_ani(
                int(current_user.firenze_client_id),
                target_ani,
            )
            if delete_ok and was_deleted:
                flash(_("Teléfono adicional eliminado."), "success")
            elif delete_ok:
                flash(_("Ese teléfono no existe en tu lista."), "info")
            else:
                flash(_("No se pudo eliminar el teléfono adicional."), "danger")
            return redirect(url_for("account.settings", tab="additional-phones"))

        if form_type == "notifications":
            current_user.notification_preferences = [
                value
                for value in request.form.getlist("notification_preferences")
                if value in notification_option_keys
            ]
            db.session.commit()
            flash(_("Preferencias de notificación actualizadas."), "success")
            return redirect(url_for("account.settings", tab="notifications"))

        previous_full_name = current_user.full_name
        previous_phone = current_user.phone

        current_user.full_name = request.form.get("full_name", "").strip() or None
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.rut = request.form.get("rut", "").strip() or None
        current_user.address = request.form.get("address", "").strip() or None
        current_user.commune = request.form.get("commune", "").strip() or None
        current_user.postal_code = request.form.get("postal_code", "").strip() or None
        requested_tarotista = request.form.get("favorite_tarotista_option", "").strip()
        current_user.favorite_tarotista_option = (
            requested_tarotista if requested_tarotista in ejecutivos_by_option else None
        )
        pref = request.form.get("preferred_payment", "").strip()
        current_user.preferred_payment = pref if pref in ("flow", "khipu") else None
        db.session.commit()

        full_name_changed = previous_full_name != current_user.full_name
        phone_changed = previous_phone != current_user.phone
        if current_user.firenze_client_id and (full_name_changed or phone_changed):
            update_payload: dict[str, str | None] = {}
            if full_name_changed:
                update_payload["full_name"] = current_user.full_name
            if phone_changed:
                update_payload["phone"] = current_user.phone

            if not update_client_profile(
                int(current_user.firenze_client_id),
                **update_payload,
            ):
                logger.warning(
                    "settings: failed to sync Firenze profile for user=%s client_id=%s changed=%s",
                    current_user.id,
                    current_user.firenze_client_id,
                    list(update_payload.keys()),
                )

        logger.info("Profile updated for user=%s", current_user.id)
        flash(_("Perfil actualizado correctamente."), "success")
        return redirect(url_for("account.settings", tab="profile"))

    additional_phones: list[str] = []
    if current_user.firenze_client_id:
        phones = list_client_anis(int(current_user.firenze_client_id))
        if phones is None:
            flash(
                _("No fue posible cargar los teléfonos adicionales desde Firenze."),
                "warning",
            )
        else:
            additional_phones = phones

    return render_template(
        "account/settings.html",
        user=current_user,
        active_tab=active_tab,
        additional_phones=additional_phones,
        ejecutivos=ejecutivos,
        notification_options=notification_options,
        selected_notification_preferences=set(current_user.notification_preferences or []),
    )


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
    """Legacy endpoint kept for compatibility; account creation is checkout-only."""
    flash(
        _("La creación de cuenta está disponible durante el checkout."),
        "info",
    )
    return redirect(url_for("pagos.index"))
