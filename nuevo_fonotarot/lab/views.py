"""Views for the lab blueprint — design experiments and home page prototypes."""

from flask import render_template

from . import lab_bp
from ..placeholder import AGENTS, PLANS, TESTIMONIALS


def _ctx():
    """Shared template context for all lab views."""
    return {"agents": AGENTS, "testimonials": TESTIMONIALS, "plans": PLANS}


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
# Checkout design experiments – one per customer type
# ---------------------------------------------------------------------------


@lab_bp.route("/checkout")
def checkout_index():
    """Overview of all three checkout design options."""
    return render_template("lab/checkout-index.html", **_ctx())


@lab_bp.route("/checkout/anonimo")
def checkout_anonimo():
    """Checkout · Opción 1: Visitante anónimo (solo email, productos digitales)."""
    return render_template("lab/checkout-anonimo.html", **_ctx())


@lab_bp.route("/checkout/conocido")
def checkout_conocido():
    """Checkout · Opción 2: Cliente registrado (email pre-llenado, pago favorito)."""
    return render_template("lab/checkout-conocido.html", **_ctx())


@lab_bp.route("/checkout/fisico")
def checkout_fisico():
    """Checkout · Opción 3: Cliente físico (dirección completa, envío anónimo)."""
    return render_template("lab/checkout-fisico.html", **_ctx())
