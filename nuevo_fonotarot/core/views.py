from flask import jsonify

from . import core_bp


@core_bp.route("/")
def hello_world():
    return jsonify({"message": "Hello, World!", "module": "core"})
