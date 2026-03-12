"""Views for the content blueprint (blog posts, static pages, and homepage)."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..extensions import limiter
from ..models import BlogPost, MinutePack, SiteSettings, StaticPage
from ..placeholder import TESTIMONIALS
from ..utils import get_agents

logger = logging.getLogger(__name__)


def _firenze_token() -> str:
    """Obtain a JWT bearer token from the Firenze API (OAuth2 password grant)."""
    api_url = current_app.config.get("FIRENZE_API_URL", "").rstrip("/")
    user = current_app.config.get("FIRENZE_API_USER", "")
    password = current_app.config.get("FIRENZE_API_PASSWORD", "")
    scopes = current_app.config.get("FIRENZE_API_SCOPES", "")

    body = urllib.parse.urlencode(
        {"username": user, "password": password, "grant_type": "password", "scope": scopes}
    ).encode()
    req = urllib.request.Request(
        f"{api_url}/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


def _firenze_get(path: str, token: str) -> tuple[int, Any]:
    """GET request to the Firenze API. Returns (status_code, body_dict)."""
    api_url = current_app.config.get("FIRENZE_API_URL", "").rstrip("/")
    req = urllib.request.Request(
        f"{api_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _firenze_post(path: str, token: str, payload: dict) -> tuple[int, Any]:
    """POST JSON to the Firenze API. Returns (status_code, body_dict)."""
    api_url = current_app.config.get("FIRENZE_API_URL", "").rstrip("/")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{api_url}{path}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _firenze_patch(path: str, token: str, payload: dict) -> tuple[int, Any]:
    """PATCH JSON to the Firenze API. Returns (status_code, body_dict)."""
    api_url = current_app.config.get("FIRENZE_API_URL", "").rstrip("/")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{api_url}{path}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _homepage_ctx() -> dict:
    """Return the shared context dict used by all homepage template variants."""
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    agents, agents_error = get_agents()
    return {
        "agents": agents,
        "agent_profiles": agents,
        "agents_error": agents_error,
        "testimonials": TESTIMONIALS,
        "minute_packs": minute_packs,
        "plans": minute_packs,  # alias used by older experiment templates
    }

blog_bp = Blueprint("blog", __name__)
content_bp = Blueprint("content", __name__)


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------


@content_bp.route("/")
def index():
    """Render the home page.

    The output is driven by the ``homepage_type`` SiteSettings key:

    * ``"static"`` — render the StaticPage whose path matches
      ``homepage_slug``.  Returns 404 if the page is missing or inactive.
    * ``"blog"``   — render the published blog post listing.
    * unset        — fall back to the hardcoded ``index.html`` template.
    """
    homepage_type = SiteSettings.get("homepage_type")

    if homepage_type == "static":
        slug = SiteSettings.get("homepage_slug", "")
        page = StaticPage.query.filter_by(path=slug, is_active=True).first()
        if page is None:
            abort(404)
        if page.template_name:
            response = make_response(render_template(page.template_name, **_homepage_ctx()))
        else:
            response = make_response(render_template("pages/page.html", page=page))
        response.headers["Cache-Control"] = "no-store"
        return response

    if homepage_type == "blog":
        posts = (
            BlogPost.query.filter_by(published=True)
            .order_by(BlogPost.published_at.desc())
            .all()
        )
        return render_template("blog/index.html", posts=posts)

    # Default: hardcoded home template.
    return render_template("index.html", **_homepage_ctx())


# ---------------------------------------------------------------------------
# Agent status API
# ---------------------------------------------------------------------------


@content_bp.route("/api/agents")
@limiter.exempt
def api_agents():
    """Return the live agent list as JSON (consumed by the homepage poller)."""
    agents, error = get_agents()
    if error == "timeout":
        return jsonify({"error": "timeout"}), 504
    if error:
        return jsonify({"error": "503"}), 503
    return jsonify(agents)


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


@blog_bp.route("/")
def listing():
    """List all published blog posts, newest first."""
    posts = (
        BlogPost.query.filter_by(published=True)
        .order_by(BlogPost.published_at.desc())
        .all()
    )
    return render_template("blog/index.html", posts=posts)


@blog_bp.route("/<slug>")
def detail(slug: str):
    """Display a single published blog post."""
    post = BlogPost.query.filter_by(slug=slug, published=True).first()
    if post is None:
        abort(404)
    return render_template("blog/detail.html", post=post)


# ---------------------------------------------------------------------------
# Promotion: free 5-minute trial via Firenze API
# ---------------------------------------------------------------------------


@content_bp.route("/promo/exito")
def promo_exito():
    """Success page shown after a free-trial promotion is activated."""
    ani = session.get("promo_ani")
    if not ani:
        return redirect(url_for("content.index"))
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    return render_template("promo_exito.html", ani=ani, minute_packs=minute_packs)


@content_bp.route("/api/promo/cobrar", methods=["POST"])
def api_promo_cobrar():
    """Check phone eligibility against the Firenze API and activate the promotion.

    Flow:
    * 2xx from ``/phone/{ani}`` → phone already registered → not eligible (409).
    * 404 from ``/phone/{ani}`` → new user → create client → store ANI in session.
    """
    data = request.get_json(silent=True) or {}
    ani = str(data.get("ani", "")).strip()

    if not ani.isdigit() or not 10 <= len(ani) <= 13:
        return jsonify({"error": "invalid_phone", "message": "Ingresa un número válido (solo dígitos, sin +)."}), 400

    try:
        token = _firenze_token()
    except Exception:
        logger.exception("Firenze token error")
        return jsonify({"error": "api_error", "message": "Error de conexión con el servicio. Inténtalo más tarde."}), 503

    try:
        status, _ = _firenze_get(f"/audiotex/fonotarot-cl/phone/{ani}", token)
    except Exception:
        logger.exception("Firenze check-phone error")
        return jsonify({"error": "api_error", "message": "Error al verificar el número. Inténtalo más tarde."}), 503

    if status < 400:
        return jsonify({"error": "not_eligible", "message": "Este número ya recibió la promoción de bienvenida."}), 409

    if status != 404:
        logger.error("Unexpected Firenze phone-check status: %s", status)
        return jsonify({"error": "api_error", "message": "Error inesperado. Inténtalo más tarde."}), 503

    # Phone not found → eligible → create client with 5 minutes (300 s)
    try:
        create_status, _ = _firenze_post(
            "/audiotex/fonotarot-cl/client/",
            token,
            {"ani": ani, "correo": f"{ani}@fonotarot.com", "segundos": 300},
        )
    except Exception:
        logger.exception("Firenze create-client error")
        return jsonify({"error": "api_error", "message": "Error al activar la promoción. Inténtalo más tarde."}), 503

    if create_status >= 400:
        logger.error("Firenze create-client returned %s", create_status)
        return jsonify({"error": "api_error", "message": "No se pudo activar la promoción. Inténtalo más tarde."}), 503

    session["promo_ani"] = ani
    return jsonify({"success": True, "redirect": url_for("content.promo_exito")})


@content_bp.route("/api/promo/actualizar-email", methods=["POST"])
def api_promo_actualizar_email():
    """Update the client's email address in the Firenze API."""
    ani = session.get("promo_ani")
    if not ani:
        return jsonify({"error": "session_expired", "message": "Sesión expirada. Recarga la página."}), 401

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "invalid_email", "message": "Ingresa un email válido."}), 400

    try:
        token = _firenze_token()
    except Exception:
        logger.exception("Firenze token error (email update)")
        return jsonify({"error": "api_error", "message": "Error de conexión. Inténtalo más tarde."}), 503

    try:
        status, _ = _firenze_patch(f"/audiotex/fonotarot-cl/client/{ani}", token, {"correo": email})
    except Exception:
        logger.exception("Firenze update-email error")
        return jsonify({"error": "api_error", "message": "Error al actualizar el email."}), 503

    if status >= 400:
        logger.error("Firenze update-email returned %s", status)
        return jsonify({"error": "api_error", "message": "No se pudo actualizar el email."}), 503

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Static pages (catch-all — must remain last)
# ---------------------------------------------------------------------------


@content_bp.route("/<path:page_path>")
def static_page(page_path: str):
    """Serve a static HTML page stored in the database.

    Supports nested paths such as ``/about-us``, ``/help``,
    ``/level1/level2``, ``/level1/help``.  The path is normalised before
    lookup so that variations in capitalisation or trailing slashes all
    resolve to the same record.
    """
    normalised = StaticPage.normalize_path(page_path)
    page = StaticPage.query.filter_by(path=normalised, is_active=True).first()
    if page is None:
        abort(404)
    if page.template_name:
        response = make_response(render_template(page.template_name, **_homepage_ctx()))
    else:
        response = make_response(render_template("pages/page.html", page=page))
    response.headers["Cache-Control"] = "no-store"
    return response
