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

from ..extensions import db, limiter, user_datastore
from ..firenze import search_client, update_client_profile
from ..log import get_logger
from ..models import BlogPost, GiftCardProduct, MinutePack, Role, SiteSettings, StaticPage
from ..placeholder import TESTIMONIALS
from ..utils import get_moon_phase_index


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
    except (ValueError, TypeError):
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




@content_bp.route("/test-emails")
def test_emails():
    from ..notifications import notify_issuer_of_issued_giftcard
    from ..models import GiftCard
    from ..extensions import db
    from flask import render_template_string

    card = db.session.get(GiftCard, 3)
    template = notify_issuer_of_issued_giftcard(card=card)
    return render_template_string(template)


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
