"""Temporary placeholder data used in the hardcoded home template and lab experiments.

Replace with DB-backed content once pages are managed via StaticPage.
"""

AGENTS = [
    {"name": "Paulina", "specialty": "Opcion 1", "status": "busy"},
    {"name": "Violeta", "specialty": "Opcion 15", "status": "online"},
    {"name": "Alex", "specialty": "Opcion 14", "status": "busy"},
    {"name": "Simone", "specialty": "Opcion 13", "status": "busy"},
    {"name": "Alvaro", "specialty": "Opcion 12", "status": "busy"},
    {"name": "Paola", "specialty": "Opcion 6", "status": "online"},
]

TESTIMONIALS = [
    {
        "text": "Tengo dos tarotistas favoritas: Simone y Paulina. Explico por qué… Simone es muy acertiva, clara para dar respuestas y muy atenta. Ya somos casi amigas, es excelente tarotista, 100% recomendable. Paulina es muy cariñosa, es acertiva; también 100 % recomendable",
        "author": "Lissette Andrade (47 años)",
        "city": "Técnico en construcción civil",
    },
    {
        "text": "Mis tarotistas preferidas son Altair y Simone. La verdad es que son asertivas en la mayoría de las preguntas. Tampoco descarto a Álvaro, Paulina y Verónica, también son muy buenos. Lo mejor es que también saben dar consejos y nos son nada antipáticos. Saben llegar al corazón de las personas.",
        "author": "Susan (48 años)",
        "city": "Peluquera",
    },
    {
        "text": "Mis favoritos son: Altair y Paola. Siempre me responde bien mis dudas y es bien asertiva y da muy buenos consejos. Dice las cosas como son y no lo que uno quiere.",
        "author": "Jorge Andres (51 años)",
        "city": "Comerciante",
    },
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
    {"minutes": 15, "price": "5.000", "description": "Consulta rápida para resolver una pregunta puntual.", "featured": False},
    {"minutes": 30, "price": "10.000", "description": "Tiempo suficiente para una lectura completa de tu situación.", "featured": True},
    {"minutes": 100, "price": "30.000", "description": "Sesión en profundidad para análisis de área de vida.", "featured": False},
    {"minutes": 250, "price": "75.000", "description": "Consulta extensa que cubre todas las áreas que necesitas.", "featured": False},
]
