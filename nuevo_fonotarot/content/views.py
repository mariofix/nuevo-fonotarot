"""Views for the content blueprint (blog posts, static pages, and homepage)."""

import json as _json
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
from flask_security.utils import login_user
from requests.exceptions import RequestException

from ..actions import process_user_registration, register_checkout_account
from ..extensions import db, limiter, user_datastore
from ..firenze import complete_promo_credit, search_client, update_client_profile
from ..log import get_logger
from ..models import BlogPost, GiftCardProduct, MinutePack, Role, SiteSettings, StaticPage
from ..placeholder import TESTIMONIALS
from ..utils import get_moon_phase_index

# SiteSettings key that tracks how many free-trial promos are left.
_PROMO_REMAINING_KEY = "promo_free_minutes_remaining"
_PROMO_INITIAL_STOCK = 36
_PROMO_DURATION_SECONDS = 300  # 5 minutes of free trial credit

logger = get_logger(__name__)


def _firenze_auth_headers() -> dict[str, str]:
    """Build Firenze auth headers using API key/secret credentials."""
    api_key = (current_app.config.get("FIRENZE_API_KEY", "") or current_app.config.get("FIRENZE_API_USER", "")).strip()
    api_secret = (
        current_app.config.get("FIRENZE_API_SECRET", "") or current_app.config.get("FIRENZE_API_PASSWORD", "")
    ).strip()
    if not api_key or not api_secret:
        raise RequestException("FIRENZE_API_KEY/FIRENZE_API_SECRET not configured")
    return {"x-api-key": api_key, "x-api-secret": api_secret}


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

    try:
        html_body = render_template(
            "email/promo_user.html",
            remaining=remaining,
        )
        with DaleksClient(daleks_url, timeout=daleks_timeout) as client:
            client.send_email(
                from_address=from_address,
                to=[email],
                subject="¡Tus 5 minutos gratuitos en Fonotarot están listos!",
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


def _homepage_ctx() -> dict:
    """Return the shared context dict used by all homepage template variants.

    Firenze public endpoint URLs are injected here so the browser can call the
    ejecutivos endpoint directly via JavaScript, avoiding per-poll server-side
    log entries.
    """
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    gift_cards = GiftCardProduct.query.filter_by(is_active=True).order_by(GiftCardProduct.minutes).all()

    api_url = current_app.config.get("FIRENZE_API_URL", "").rstrip("/")
    firenze_ejecutivos_url = f"{api_url}/api/v1/public/ejecutivos" if api_url else ""

    try:
        ejecutivos = _json.loads(current_app.config.get("FT_EJECUTIVOS", []))
    except ValueError, TypeError:
        logger.warning("SiteSettings 'ejecutivos' is not valid JSON; tarotistas section will be empty")
        ejecutivos = []

    latest_posts = BlogPost.query.filter_by(published=True).order_by(BlogPost.published_at.desc()).limit(3).all()

    return {
        "firenze_ejecutivos_url": firenze_ejecutivos_url,
        "ejecutivos": ejecutivos,
        "testimonials": TESTIMONIALS,
        "minute_packs": minute_packs,
        "gift_cards": gift_cards,
        "plans": minute_packs,  # alias used by older experiment templates
        "current_moon_phase": get_moon_phase_index(),
        "latest_posts": latest_posts,
    }


blog_bp = Blueprint("blog", __name__)
logger.debug("blog_bp: blueprint created")

content_bp = Blueprint("content", __name__)
logger.debug("content_bp: blueprint created")


# ---------------------------------------------------------------------------
# robots.txt & sitemap.xml
# ---------------------------------------------------------------------------


@content_bp.route("/robots.txt")
def robots_txt():
    """Serve a dynamic robots.txt."""
    site_url = f"https://{current_app.config.get('TRUSTED_HOSTS', ['localhost'])[0]}"
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "Disallow: /ft-admin/",
        "Disallow: /account/",
        "Disallow: /api/",
        "Disallow: /promo/",
        "",
        f"Sitemap: {site_url}/sitemap.xml",
    ]
    resp = make_response("\n".join(lines) + "\n")
    resp.headers["Content-Type"] = "text/plain; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@content_bp.route("/sitemap.xml")
def sitemap_xml():
    """Generate a dynamic XML sitemap with homepage, blog posts, and static pages."""

    site_url = f"https://{current_app.config.get('TRUSTED_HOSTS', ['localhost'])[0]}"
    blog_prefix = current_app.config.get("BLOG_URL_PREFIX", "/blog")

    urls = []

    # Homepage
    urls.append(
        {
            "loc": f"{site_url}/",
            "changefreq": "daily",
            "priority": "1.0",
        }
    )

    # Blog listing
    urls.append(
        {
            "loc": f"{site_url}{blog_prefix}/",
            "changefreq": "daily",
            "priority": "0.8",
        }
    )

    # Published blog posts
    posts = BlogPost.query.filter_by(published=True).order_by(BlogPost.published_at.desc()).all()
    for post in posts:
        entry = {
            "loc": f"{site_url}{blog_prefix}/{post.slug}",
            "changefreq": "monthly",
            "priority": "0.7",
        }
        if post.updated_at:
            entry["lastmod"] = post.updated_at.strftime("%Y-%m-%d")
        urls.append(entry)

    # Active static pages (excluding homepage-flagged ones)
    pages = StaticPage.query.filter_by(is_active=True, is_homepage=False).all()
    for page in pages:
        entry = {
            "loc": f"{site_url}/{page.path}",
            "changefreq": "monthly",
            "priority": "0.5",
        }
        if page.updated_at:
            entry["lastmod"] = page.updated_at.strftime("%Y-%m-%d")
        urls.append(entry)

    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in urls:
        xml_parts.append("  <url>")
        xml_parts.append(f"    <loc>{u['loc']}</loc>")
        if "lastmod" in u:
            xml_parts.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        xml_parts.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        xml_parts.append(f"    <priority>{u['priority']}</priority>")
        xml_parts.append("  </url>")
    xml_parts.append("</urlset>")

    resp = make_response("\n".join(xml_parts))
    resp.headers["Content-Type"] = "application/xml; charset=utf-8"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ---------------------------------------------------------------------------
# Homepage
# ---------------------------------------------------------------------------


@content_bp.route("/")
def index():
    """Render the home page.

    Priority order:

    1. ``homepage_type == "blog"`` SiteSetting → published blog post listing.
    2. A ``StaticPage`` with ``is_homepage=True`` and ``is_active=True`` →
       render its database content via ``pages/page.html``.
    3. Default → the hardcoded ``index.html`` template.
    """
    if SiteSettings.get("homepage_type") == "blog":
        posts = BlogPost.query.filter_by(published=True).order_by(BlogPost.published_at.desc()).all()
        return render_template("blog/index.html", posts=posts)

    page = StaticPage.query.filter_by(is_homepage=True, is_active=True).first()
    if page is not None:
        response = make_response(render_template("pages/page.html", page=page))
        response.headers["Cache-Control"] = "no-store"
        return response

    # Default: hardcoded home template.
    return render_template("index.html", **_homepage_ctx())


# ---------------------------------------------------------------------------
# Blog
# ---------------------------------------------------------------------------


@blog_bp.route("/")
def listing():
    """List all published blog posts, newest first."""
    posts = BlogPost.query.filter_by(published=True).order_by(BlogPost.published_at.desc()).all()
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


@content_bp.route("/promo/exito", methods=["GET", "POST"])
@limiter.limit("30 per hour")
def promo_exito():
    """Success page shown after a free-trial promotion is activated."""
    ani = session.get("promo_ani")
    if not ani:
        return redirect(url_for("content.index"))

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip()
        if not email or "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "invalid_email", "message": "Ingresa un email válido."}), 400

        response_body, status = _finalize_promo_email(email)
        return jsonify(response_body), status

    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    return render_template("promo_exito.html", ani=ani, minute_packs=minute_packs)


@content_bp.route("/api/promo/cobrar", methods=["POST"])
@limiter.limit("5 per hour; 2 per minute")
def api_promo_cobrar():
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


@content_bp.route("/api/promo/actualizar-email", methods=["POST"])
@limiter.limit("10 per hour")
def api_promo_actualizar_email():
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
    response = make_response(render_template("pages/page.html", page=page))
    response.headers["Cache-Control"] = "no-store"
    return response
