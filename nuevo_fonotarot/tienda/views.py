from flask import jsonify

from . import tienda_bp


@tienda_bp.route("/")
def hello_world():
    return jsonify({"message": "Hello, World!", "module": "tienda"})
