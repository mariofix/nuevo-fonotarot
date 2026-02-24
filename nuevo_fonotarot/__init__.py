from flask import Flask


def create_app():
    app = Flask(__name__)

    from .core import core_bp
    app.register_blueprint(core_bp)

    from .tienda import tienda_bp
    app.register_blueprint(tienda_bp)

    return app
