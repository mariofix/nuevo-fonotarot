from decimal import Decimal
import importlib
from types import SimpleNamespace

from flask_security.models import fsqla_v3 as fsqla

from nuevo_fonotarot import create_flask

_TEST_APP = None

original_set_db_info = fsqla.FsModels.set_db_info


def safe_set_db_info(*args, **kwargs):
    try:
        return original_set_db_info(*args, **kwargs)
    except Exception as exc:
        if "already defined for this MetaData instance" in str(exc):
            return None
        raise


def _make_testing_app(monkeypatch):
    global _TEST_APP
    if _TEST_APP is not None:
        return _TEST_APP

    monkeypatch.setattr(fsqla.FsModels, "set_db_info", safe_set_db_info)
    _TEST_APP = create_flask("testing")
    return _TEST_APP


def _pagos_views():
    return importlib.import_module("nuevo_fonotarot.tienda.pagos.views")


class _QueryStub:
    def __init__(self, order=None, packs=None):
        self._order = order
        self._packs = packs or []

    def filter_by(self, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._packs)

    def first_or_404(self):
        return self._order


def test_orden_estado_shows_refresh_message_when_payment_is_pending(monkeypatch):
    app = _make_testing_app(monkeypatch)
    pagos_views = _pagos_views()
    order = SimpleNamespace(
        id=1001,
        merchants_id="ret_pending",
        status="pending",
        payment_status="pending",
        transaction_id="txn_pending",
        total_display="$9.990",
        provider="khipu",
        amount=Decimal("9990"),
        items=[],
    )
    packs = [SimpleNamespace(id=1, minutes=15, price_display="$9.990", description=None, is_featured=False)]

    monkeypatch.setattr(pagos_views, "Order", SimpleNamespace(query=_QueryStub(order=order)))
    monkeypatch.setattr(
        pagos_views,
        "MinutePack",
        SimpleNamespace(query=_QueryStub(packs=packs), minutes=0),
    )
    monkeypatch.setattr(pagos_views, "_summarize_order_minutes", lambda items: 0)

    with app.test_client() as client:
        response = client.get("/tienda/orden/ret_pending/")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Estamos esperando la confirmación del pago" in body
    assert "window.location.reload" not in body
    assert "Pago en proceso" in body


def test_orden_estado_shows_paid_purchase_summary_and_offers(monkeypatch):
    app = _make_testing_app(monkeypatch)
    pagos_views = _pagos_views()
    order = SimpleNamespace(
        id=1002,
        merchants_id="ret_paid",
        status="paid",
        payment_status="succeeded",
        transaction_id="txn_paid",
        total_display="$19.980",
        provider="flow",
        amount=Decimal("19980"),
        items=[
            SimpleNamespace(item_type="minute_pack", item_id=1, name="15 minutos de tarot", quantity=2),
            SimpleNamespace(item_type="minute_pack", item_id=2, name="5 minutos de tarot", quantity=1),
        ],
    )
    packs = [
        SimpleNamespace(id=1, minutes=15, price_display="$9.990", description="Pack 15", is_featured=True),
        SimpleNamespace(id=2, minutes=5, price_display="$4.990", description=None, is_featured=False),
    ]

    monkeypatch.setattr(pagos_views, "Order", SimpleNamespace(query=_QueryStub(order=order)))
    monkeypatch.setattr(
        pagos_views,
        "MinutePack",
        SimpleNamespace(query=_QueryStub(packs=packs), minutes=0),
    )
    monkeypatch.setattr(pagos_views, "_summarize_order_minutes", lambda items: 35)

    with app.test_client() as client:
        response = client.get("/tienda/orden/ret_paid/")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Tu compra ya está lista" in body
    assert "35" in body
    assert "+56 2 2230 1515" in body
    assert "Comprar de nuevo" in body
    assert "Compra con un clic" in body
    assert "Crear cuenta" in body
