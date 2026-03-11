"""Views for the lab blueprint — design experiments and home page prototypes."""

from flask import render_template

from . import lab_bp
from ..placeholder import PLANS, TESTIMONIALS


def _ctx():
    """Shared template context for all lab views."""
    return {"agents": [], "testimonials": TESTIMONIALS, "plans": PLANS}


@lab_bp.route("/home-full")
def home_full():
    """Home v1 base enriched with sections from v2, v4, and v6."""
    return render_template("home-full.html", **_ctx())


@lab_bp.route("/new-home-full")
def new_home_full():
    """Home v2 base enriched with sections from v1, v4, and v6."""
    return render_template("new-home-full.html", **_ctx())


@lab_bp.route("/home1")
def home1():
    """Místico Oscuro."""
    return render_template("old-experiments/home1.html", **_ctx())


@lab_bp.route("/home2")
def home2():
    """Luna Suave."""
    return render_template("old-experiments/home2.html", **_ctx())


@lab_bp.route("/home3")
def home3():
    """Moderno Profesional."""
    return render_template("old-experiments/home3.html", **_ctx())


@lab_bp.route("/home4")
def home4():
    """Bosque Esmeralda."""
    return render_template("old-experiments/home4.html", **_ctx())


@lab_bp.route("/home5")
def home5():
    """Electra (tech-mystic)."""
    return render_template("old-experiments/home5.html", **_ctx())


@lab_bp.route("/home6")
def home6():
    """Bordó Oscuro (wine luxury)."""
    return render_template("old-experiments/home6.html", **_ctx())


@lab_bp.route("/home7")
def home7():
    """Puesta del Sol (conversion)."""
    return render_template("old-experiments/home7.html", **_ctx())


@lab_bp.route("/home8")
def home8():
    """Índigo Místico (bento grid)."""
    return render_template("old-experiments/home8.html", **_ctx())


# ---------------------------------------------------------------------------
# Checkout design experiments
# ---------------------------------------------------------------------------


@lab_bp.route("/checkout-a")
def checkout_a():
    """Checkout A – Stepper (multi-step wizard with progress bar)."""
    return render_template("lab/checkout-a.html")


@lab_bp.route("/checkout-b")
def checkout_b():
    """Checkout B – Accordion (collapsible sections, single page)."""
    return render_template("lab/checkout-b.html")


@lab_bp.route("/checkout-c")
def checkout_c():
    """Checkout C – Split Screen (immersive two-panel layout)."""
    return render_template("lab/checkout-c.html")
