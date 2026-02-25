"""Views for the home blueprint."""

from flask import render_template

from . import home_bp

# Sample agents shown on the home page (replace with DB-backed data as needed)
AGENTS = [
    {"name": "Valentina", "specialty": "Tarot del Amor", "status": "online"},
    {"name": "Camila", "specialty": "Tarot Gitano", "status": "online"},
    {"name": "Javiera", "specialty": "Tarot Marsella", "status": "busy"},
    {"name": "Francisca", "specialty": "Tarot Kármico", "status": "online"},
    {"name": "Catalina", "specialty": "Tarot Intuitivo", "status": "busy"},
    {"name": "Constanza", "specialty": "Runas Nórdicas", "status": "online"},
]

TESTIMONIALS = [
    {
        "text": "Valentina fue increíble, me dio una lectura muy precisa sobre mi situación laboral. ¡Totalmente recomendada!",
        "author": "María G.",
        "city": "Santiago",
    },
    {
        "text": "Llevaba meses con dudas sobre mi relación y Camila me ayudó a verlo todo con claridad. Una experiencia única.",
        "author": "Daniela R.",
        "city": "Valparaíso",
    },
    {
        "text": "Nunca había llamado a un servicio de tarot y quedé gratamente sorprendida. La consulta fue muy profesional y reveladora.",
        "author": "Andrea M.",
        "city": "Concepción",
    },
    {
        "text": "Francisca tiene un don especial. Me habló de cosas que nadie podría saber. La llamo cada vez que necesito orientación.",
        "author": "Carolina P.",
        "city": "Viña del Mar",
    },
]

PLANS = [
    {
        "minutes": 15,
        "price": "4.990",
        "description": "Consulta rápida para resolver una pregunta puntual.",
        "featured": False,
    },
    {
        "minutes": 30,
        "price": "8.990",
        "description": "Tiempo suficiente para una lectura completa de tu situación.",
        "featured": False,
    },
    {
        "minutes": 60,
        "price": "14.990",
        "description": "Sesión en profundidad para análisis de área de vida.",
        "featured": True,
    },
    {
        "minutes": 120,
        "price": "24.990",
        "description": "Consulta extensa que cubre todas las áreas que necesitas.",
        "featured": False,
    },
]


@home_bp.route("/")
def index():
    """Render the Fonotarot home page."""
    return render_template(
        "home.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home1")
def home1():
    """Render alternative home page design 1 – Místico Oscuro."""
    return render_template(
        "home1.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home2")
def home2():
    """Render alternative home page design 2 – Luna Suave."""
    return render_template(
        "home2.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home3")
def home3():
    """Render alternative home page design 3 – Moderno Profesional."""
    return render_template(
        "home3.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home4")
def home4():
    """Render alternative home page design 4 – Bosque Esmeralda."""
    return render_template(
        "home4.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home5")
def home5():
    """Render alternative home page design 5 – Electra (tech-mystic)."""
    return render_template(
        "home5.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home6")
def home6():
    """Render alternative home page design 6 – Bordó Oscuro (wine luxury)."""
    return render_template(
        "home6.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home7")
def home7():
    """Render alternative home page design 7 – Puesta del Sol (conversion)."""
    return render_template(
        "home7.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home8")
def home8():
    """Render alternative home page design 8 – Índigo Místico (bento grid)."""
    return render_template(
        "home8.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )


@home_bp.route("/home-full")
def home_full():
    """Render the full showcase page – /home1 base enriched with sections from /home2, /home4 and /home6."""
    return render_template(
        "home-full.html",
        agents=AGENTS,
        testimonials=TESTIMONIALS,
        plans=PLANS,
    )
