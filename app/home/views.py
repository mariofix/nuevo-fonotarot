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
