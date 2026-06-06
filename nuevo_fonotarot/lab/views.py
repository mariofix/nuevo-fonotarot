"""Views for the lab blueprint — design experiments and home page prototypes."""

from flask import render_template

from ..log import get_logger
from ..models import BlogPost, GiftCardProduct, MinutePack, Product
from ..placeholder import PLANS, TESTIMONIALS
from . import lab_bp

logger = get_logger(__name__)


def _ctx():
    """Shared template context for all lab views."""
    return {"agents": [], "testimonials": TESTIMONIALS, "plans": PLANS}


def _store_preview_ctx() -> dict:
    """Shared store context for tienda lab previews."""
    minute_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes.asc()).all()
    gift_cards = GiftCardProduct.query.filter_by(is_active=True).order_by(GiftCardProduct.price.asc()).limit(4).all()
    featured_products = (
        Product.query.filter_by(is_active=True)
        .order_by(Product.is_featured.desc(), Product.created_at.desc())
        .limit(6)
        .all()
    )
    return {
        "minute_packs": minute_packs,
        "gift_cards": gift_cards,
        "featured_products": featured_products,
    }


@lab_bp.route("/home-full")
def home_full():
    """Home v1 base enriched with sections from v2, v4, and v6."""
    logger.debug("lab: rendering home-full")
    return render_template("home-full.html", **_ctx())


@lab_bp.route("/new-home-full")
def new_home_full():
    """Home v2 base enriched with sections from v1, v4, and v6."""
    logger.debug("lab: rendering new-home-full")
    return render_template("new-home-full.html", **_ctx())


@lab_bp.route("/tienda-home")
def tienda_home():
    """Tienda home redesign preview based on blueprint sketch."""
    logger.debug("lab: rendering tienda-home")
    return render_template("lab/tienda-home.html", **_store_preview_ctx(), **_ctx())


@lab_bp.route("/tienda-home-v2")
def tienda_home_v2():
    """Tienda home redesign preview v2 without hero and with home eye-candy accents."""
    logger.debug("lab: rendering tienda-home-v2")
    return render_template("lab/tienda-home-v2.html", **_store_preview_ctx(), **_ctx())


@lab_bp.route("/home1")
def home1():
    """Místico Oscuro."""
    logger.debug("lab: rendering home1")
    return render_template("old-experiments/home1.html", **_ctx())


@lab_bp.route("/home2")
def home2():
    """Luna Suave."""
    logger.debug("lab: rendering home2")
    return render_template("old-experiments/home2.html", **_ctx())


@lab_bp.route("/home3")
def home3():
    """Moderno Profesional."""
    logger.debug("lab: rendering home3")
    return render_template("old-experiments/home3.html", **_ctx())


@lab_bp.route("/home4")
def home4():
    """Bosque Esmeralda."""
    logger.debug("lab: rendering home4")
    return render_template("old-experiments/home4.html", **_ctx())


@lab_bp.route("/home5")
def home5():
    """Electra (tech-mystic)."""
    logger.debug("lab: rendering home5")
    return render_template("old-experiments/home5.html", **_ctx())


@lab_bp.route("/home6")
def home6():
    """Bordó Oscuro (wine luxury)."""
    logger.debug("lab: rendering home6")
    return render_template("old-experiments/home6.html", **_ctx())


@lab_bp.route("/home7")
def home7():
    """Puesta del Sol (conversion)."""
    logger.debug("lab: rendering home7")
    return render_template("old-experiments/home7.html", **_ctx())


@lab_bp.route("/home8")
def home8():
    """Índigo Místico (bento grid)."""
    logger.debug("lab: rendering home8")
    return render_template("old-experiments/home8.html", **_ctx())


# ---------------------------------------------------------------------------
# Checkout design experiments
# ---------------------------------------------------------------------------


def _blog_posts():
    """Return published posts for blog lab views, newest first."""
    return BlogPost.query.filter_by(published=True).order_by(BlogPost.published_at.desc()).all()


# ---------------------------------------------------------------------------
# Blog design experiments
# ---------------------------------------------------------------------------


@lab_bp.route("/blog-a")
def blog_a():
    """Blog A — Arcana Dispatch: numbered editorial list."""
    logger.debug("lab: rendering blog-a")
    return render_template("old-experiments/blog-a.html", posts=_blog_posts())


@lab_bp.route("/blog-b")
def blog_b():
    """Blog B — Lectura: typographic reading-room list."""
    logger.debug("lab: rendering blog-b")
    return render_template("old-experiments/blog-b.html", posts=_blog_posts())


@lab_bp.route("/blog-c")
def blog_c():
    """Blog C — Arcana Grid: immersive photo mosaic."""
    logger.debug("lab: rendering blog-c")
    return render_template("old-experiments/blog-c.html", posts=_blog_posts())


# ---------------------------------------------------------------------------
# Checkout design experiments
# ---------------------------------------------------------------------------


@lab_bp.route("/checkout-a")
def checkout_a():
    """Checkout A - Stepper (multi-step wizard with progress bar)."""
    logger.debug("lab: rendering checkout-a")
    return render_template("lab/checkout-a.html")


@lab_bp.route("/checkout-b")
def checkout_b():
    """Checkout B - Accordion (collapsible sections, single page)."""
    logger.debug("lab: rendering checkout-b")
    return render_template("lab/checkout-b.html")


@lab_bp.route("/checkout-c")
def checkout_c():
    """Checkout C - Split Screen (immersive two-panel layout)."""
    logger.debug("lab: rendering checkout-c")
    return render_template("lab/checkout-c.html")
