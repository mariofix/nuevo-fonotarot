"""Physical product and cart views."""

import random

from flask import redirect, render_template, url_for

from ...models import MinutePack, Product
from . import productos_bp


@productos_bp.route("/")
def index():
    # TODO: product listing
    return redirect(url_for("pagos.index"))


@productos_bp.route("/<slug>")
def detalle(slug: str):
    product = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    active_packs = MinutePack.query.filter_by(is_active=True).order_by(MinutePack.minutes).all()
    other_active_products = Product.query.filter(Product.is_active.is_(True), Product.id != product.id).all()
    other_products = random.sample(other_active_products, k=min(5, len(other_active_products)))
    return render_template(
        "tienda/producto_detalle.html",
        product=product,
        other_products=other_products,
        minute_packs=active_packs,
    )


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
