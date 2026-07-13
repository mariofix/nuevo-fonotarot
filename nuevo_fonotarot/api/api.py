from flask import Blueprint, jsonify, request, session, url_for
from ..extensions import limiter, csrf, db
from ..log import get_logger
from ..firenze import search_client_data, search_client, search_credits
from ..promo_helpers import (
    _promo_claim_remaining,
    _complete_promo_claim,
    _send_admin_promo_notification,
    _finalize_promo_email,
)

logger = get_logger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api/v1/")
csrf.exempt(api_bp)
logger.debug("api_bp: blueprint created with url_prefix=%r", api_bp.url_prefix)


@api_bp.route("/consulta-saldo", methods=["POST"])
@limiter.limit("10 per hour; 24 per day")
def consulta_saldo():
    """Consulta Saldo en Firenze"""

    data = request.get_json(silent=True) or {}
    ani = str(data.get("ani", "")).strip()

    if not ani.isdigit() or not 10 <= len(ani) <= 13:
        return jsonify({"error": "invalid_phone", "message": "Ingresa un número válido (solo dígitos, sin +)."}), 400

    data = {"status": "not_found", "saldo": 0}

    if client := search_credits(ani=ani):
        if isinstance(client, int):
            data["status"] = "ok"
            data["saldo"] = client

    return jsonify(data)


@api_bp.route("/promo/cobrar", methods=["POST"])
@limiter.limit("5 per hour; 2 per minute")
def promo_cobrar():
    """Check phone eligibility against Firenze and activate the free minutes.

    Flow:
    * Found via ``/api/v1/clients/search`` with ``ani`` → already registered → not eligible (409).
    * Not found → reserve promo stock, complete the promo credit in Firenze, and store the ANI/client_id in session.
    """

    data = request.get_json(silent=True) or {}
    ani = str(data.get("ani", "")).strip()

    if not ani.isdigit() or not 10 <= len(ani) <= 13:
        return jsonify({"error": "invalid_phone", "message": "Ingresa un número válido (solo dígitos, sin +)."}), 400

    if search_client(ani=ani) is not None:
        return jsonify({"error": "not_eligible", "message": "Este número ya recibió la promoción de bienvenida."}), 409

    # Check and atomically lock the promo stock counter.
    decremented, remaining = _promo_claim_remaining()
    if not decremented:
        return jsonify({"error": "exhausted", "message": "La promoción ya no está disponible. ¡Llegaste tarde!"}), 409

    response_body, status = _complete_promo_claim(ani)
    if status >= 400:
        db.session.rollback()
        return jsonify(response_body), status

    client_id = int(response_body["client_id"])
    db.session.commit()

    session["promo_ani"] = ani
    session["promo_remaining"] = remaining
    session["promo_client_id"] = client_id
    session.pop("promo_completed", None)
    session.pop("promo_email", None)
    _send_admin_promo_notification(ani, remaining, client_id)

    return jsonify({"success": True, "redirect": url_for("content.promo_exito")})


@api_bp.route("/promo/actualizar-email", methods=["POST"])
@limiter.limit("10 per hour")
def promo_actualizar_email():
    """Compatibility endpoint for completing the promo activation."""

    ani = session.get("promo_ani")
    if not ani:
        return jsonify({"error": "session_expired", "message": "Sesión expirada. Recarga la página."}), 401

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "invalid_email", "message": "Ingresa un email válido."}), 400

    response_body, status = _finalize_promo_email(email)
    return jsonify(response_body), status


@api_bp.route("/limiter-status", methods=["GET"])
@limiter.exempt
def general_status():
    import time

    backend = limiter.storage  # the MemoryStorage instance
    now = time.time()

    entries = []
    for key, count in backend.storage.items():
        expiry = backend.expirations.get(key)
        entries.append({
            "key": key,
            "count": count,
            "expires_in": round(expiry - now, 1) if expiry else None,
        })

    return jsonify(entries)
