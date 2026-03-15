"""Physical product and cart views — to be implemented."""

from flask import redirect, url_for

from . import productos_bp


@productos_bp.route("/")
def index():
    # TODO: product listing
    return redirect(url_for("pagos.index"))


@productos_bp.route("/<slug>")
def detalle(slug: str):
    # TODO: product detail page
    return redirect(url_for("pagos.index"))


@productos_bp.route("/carrito/")
def carrito():
    # TODO: shopping cart
    return redirect(url_for("pagos.index"))


@productos_bp.route("/carrito/agregar", methods=["POST"])
def agregar():
    # TODO: add item to cart
    return redirect(url_for("pagos.index"))


@productos_bp.route("/carrito/eliminar", methods=["POST"])
def eliminar():
    # TODO: remove item from cart
    return redirect(url_for("pagos.index"))


@productos_bp.route("/carrito/vaciar", methods=["POST"])
def vaciar():
    # TODO: empty the cart
    return redirect(url_for("pagos.index"))


@productos_bp.route("/checkout/", methods=["GET", "POST"])
def checkout():
    # TODO: cart checkout
    return redirect(url_for("pagos.index"))
