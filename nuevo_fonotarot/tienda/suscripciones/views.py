"""Subscription views — to be implemented."""

from flask import redirect, url_for

from . import suscripciones_bp


@suscripciones_bp.route("/")
def index():
    # TODO: subscription plan listing
    return redirect(url_for("pagos.index"))


@suscripciones_bp.route("/<int:plan_id>/link-pago", methods=["GET", "POST"])
def link_pago(plan_id: int):
    # TODO: generate and send subscription payment link
    return redirect(url_for("pagos.index"))


@suscripciones_bp.route("/pago/<int:order_id>/iniciar")
def iniciar_pago(order_id: int):
    # TODO: initiate payment for a subscription order (user clicks emailed link)
    return redirect(url_for("pagos.index"))
