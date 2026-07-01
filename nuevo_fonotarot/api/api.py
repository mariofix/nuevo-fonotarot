from flask import Blueprint, jsonify, request
from ..extensions import limiter, csrf
from ..log import get_logger
from ..firenze import search_client_data

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

    if client := search_client_data(ani=ani):
        found = client.get("found", False)
        if found:
            data["status"] = "ok"
            data["saldo"] = client["credits"]

    return jsonify(data)
