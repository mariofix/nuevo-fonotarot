import math
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request, session, url_for
from flask_login import login_required
from flask_security import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import csrf, db, limiter
from ..firenze import search_client, search_client_data, search_credits
from ..log import get_logger
from ..promo_helpers import (
    _complete_promo_claim,
    _finalize_promo_email,
    _promo_claim_remaining,
    _send_admin_promo_notification,
)

logger = get_logger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api/v1/")
internal_bp = Blueprint("internal_api", __name__, url_prefix="/api")
csrf.exempt(api_bp)
csrf.exempt(internal_bp)
logger.debug("api_bp: blueprint created with url_prefix=%r", api_bp.url_prefix)
logger.debug("internal_bp: blueprint created with url_prefix=%r", internal_bp.url_prefix)


@internal_bp.route("/internal/orders-summary", methods=["GET"])
def orders_summary():
    """Return the current store's sales aggregate to trusted sibling instances."""
    merchant_key = current_app.config.get("MERCHANTS_KEY")
    if not merchant_key:
        return jsonify({"error": "merchant_federation_disabled"}), 503

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "", 1).strip() if auth_header else ""
    if not token:
        return jsonify({"error": "missing_authorization"}), 401

    serializer = URLSafeTimedSerializer(
        current_app.config["MERCHANTS_KEY"],
        salt=current_app.config["SECRET_KEY"],
    )
    try:
        payload = serializer.loads(token, max_age=current_app.config.get("MERCHANTS_TOKEN_TTL_SECONDS", 60))
    except (BadSignature, SignatureExpired):
        return jsonify({"error": "invalid_or_expired_token"}), 401

    if payload.get("scope") != "orders-summary":
        return jsonify({"error": "invalid_scope"}), 401

    from ..admin import SecureAdminIndexView

    view = SecureAdminIndexView()
    now = datetime.now()

    start_ms = request.args.get("start", type=float)
    end_ms = request.args.get("end", type=float)
    try:
        if start_ms is not None and not math.isfinite(start_ms):
            start_ms = None
        if end_ms is not None and not math.isfinite(end_ms):
            end_ms = None
        start_dt = (
            datetime.fromtimestamp(start_ms / 1000)
            if start_ms is not None
            else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        )
        end_dt = datetime.fromtimestamp(end_ms / 1000) if end_ms is not None else now
    except (TypeError, ValueError, OSError):
        return jsonify({"error": "invalid start/end"}), 400

    granularity = request.args.get("granularity") or "day"
    if end_dt <= start_dt:
        return jsonify({"error": "end must be after start"}), 400

    series = view._build_sales_series(start_dt, end_dt, granularity)
    return jsonify(
        {
            "catalog_stats": view._catalog_stats_payload(),
            "sales_series": {"granularity": granularity, "series": series},
        }
    )


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
        entries.append(
            {
                "key": key,
                "count": count,
                "expires_in": round(expiry - now, 1) if expiry else None,
            }
        )

    return jsonify(entries)


@api_bp.route("/checkout/preview-discount", methods=["POST"])
@limiter.limit("5 per minute")
def preview_discount():
    from flask_babel import _

    from ..models import DiscountCode, GiftCardProduct, MinutePack, Product
    from ..tienda.utils import apply_discount

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    code_str = data.get("discount_code", "").strip()
    item_type = data.get("item_type")
    item_id = data.get("item_id")

    if not code_str or not item_type or not item_id:
        return jsonify({"error": _("Faltan parámetros.")}), 400

    discount_obj = DiscountCode.query.filter_by(code=code_str).first()
    if not discount_obj or not discount_obj.is_valid():
        return jsonify({"error": _("Código de descuento inválido o expirado.")}), 400

    price = None
    currency = None

    models_map = {
        "minute_pack": MinutePack,
        "gift_card": GiftCardProduct,
        "product": Product,
    }

    if item_type in models_map:
        item = models_map[item_type].query.get(item_id)
        if item:
            price = item.price
            currency = item.currency

    if price is None:
        return jsonify({"error": _("Producto no encontrado.")}), 404

    discount_amount = apply_discount(price, currency, discount_obj)
    if discount_amount <= 0:
        return jsonify({"error": _("El código de descuento no es aplicable a este producto.")}), 400

    final_price = price - discount_amount

    return jsonify(
        {
            "success": True,
            "discount_amount": str(discount_amount),
            "final_price": str(final_price),
            "discount_type": discount_obj.discount_type,
            "discount_value": str(discount_obj.discount_value),
            "currency": currency,
        }
    )


@api_bp.route("/push/subscribe", methods=["POST"])
@login_required
def subscribe():
    from ..models import PushSubscription, PushSubscriptionType

    data = request.get_json()
    sub = PushSubscription.query.filter_by(endpoint=data["endpoint"]).first()
    if sub:
        sub.p256dh = data["keys"]["p256dh"]
        sub.auth = data["keys"]["auth"]
    else:
        sub = PushSubscription(
            client_id=current_user.firenze_client_id,
            push_type=PushSubscriptionType.DEFAULT.value,
            endpoint=data["endpoint"],
            p256dh=data["keys"]["p256dh"],
            auth=data["keys"]["auth"],
            user_agent=request.user_agent.string[:256],
        )
        db.session.add(sub)
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    from ..models import PushSubscription

    data = request.get_json()
    PushSubscription.query.filter_by(client_id=current_user.firenze_client_id, endpoint=data.get("endpoint")).delete()
    db.session.commit()
    return jsonify({"ok": True})
