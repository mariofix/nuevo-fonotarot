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


class _GiftCardQueryStub:
    def __init__(self, gift_card):
        self._gift_card = gift_card

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self._gift_card


def test_canjear_allows_admin_issued_card_without_order(monkeypatch):
    app = _make_testing_app(monkeypatch)
    tarjetas_views = __import__("nuevo_fonotarot.tienda.tarjetas.views", fromlist=["*"])

    gift_card = SimpleNamespace(order_id=None, status="issued")
    user = SimpleNamespace(id=1, is_authenticated=True)
    calls = {"redeem": 0, "get": 0}

    monkeypatch.setattr(tarjetas_views, "current_user", user)
    monkeypatch.setattr(tarjetas_views, "GiftCard", SimpleNamespace(query=_GiftCardQueryStub(gift_card)))
    monkeypatch.setattr(
        tarjetas_views.db.session, "get", lambda *args, **kwargs: calls.__setitem__("get", calls["get"] + 1)
    )

    def fake_redeem(*, gift_card, user):
        calls["redeem"] += 1
        return True, "ok"

    monkeypatch.setattr(tarjetas_views, "redeem_gift_card", fake_redeem)

    with app.test_client() as client:
        response = client.post("/tienda/tarjetas/canjear", data={"code": "ABC123"})

    assert response.status_code == 302
    assert calls["redeem"] == 1
    assert calls["get"] == 0


def test_canjear_blocks_linked_card_until_paid(monkeypatch):
    app = _make_testing_app(monkeypatch)
    tarjetas_views = __import__("nuevo_fonotarot.tienda.tarjetas.views", fromlist=["*"])

    gift_card = SimpleNamespace(order_id=999, status="issued")
    user = SimpleNamespace(id=1, is_authenticated=True)
    calls = {"redeem": 0}
    pending_order = SimpleNamespace(payment_status="pending")

    monkeypatch.setattr(tarjetas_views, "current_user", user)
    monkeypatch.setattr(tarjetas_views, "GiftCard", SimpleNamespace(query=_GiftCardQueryStub(gift_card)))
    monkeypatch.setattr(tarjetas_views.db.session, "get", lambda *args, **kwargs: pending_order)

    def fake_redeem(*, gift_card, user):
        calls["redeem"] += 1
        return True, "ok"

    monkeypatch.setattr(tarjetas_views, "redeem_gift_card", fake_redeem)

    with app.test_client() as client:
        response = client.post("/tienda/tarjetas/canjear", data={"code": "ABC123"})

    assert response.status_code == 302
    assert calls["redeem"] == 0
