"""Views for the content blueprint (blog posts, static pages, and homepage)."""

from flask import Blueprint, abort, jsonify, make_response, render_template

from ..extensions import limiter
from ..models import BlogPost, MinutePack, SiteSettings, StaticPage
from ..placeholder import TESTIMONIALS
from ..utils import get_agents

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
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    agents, agents_error = get_agents()
    return render_template(
        "index.html",
        agents=agents,
        agent_profiles=agents,
        agents_error=agents_error,
        testimonials=TESTIMONIALS,
        minute_packs=minute_packs,
    )


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
