from types import SimpleNamespace

from flask_security.models import fsqla_v3 as fsqla

from nuevo_fonotarot.extensions import db

original_set_db_info = fsqla.FsModels.set_db_info


def safe_set_db_info(*args, **kwargs):
    try:
        return original_set_db_info(*args, **kwargs)
    except Exception as exc:
        if "already defined for this MetaData instance" in str(exc):
            return None
        raise


fsqla.FsModels.set_db_info = safe_set_db_info
fsqla.FsModels.set_db_info(db, user_table_name="users", role_table_name="roles")

from nuevo_fonotarot import signals


def test_post_purchase_process_posts_seconds_using_quantity(monkeypatch):
    calls: dict[str, object] = {}
    order = SimpleNamespace(
        id=101,
        payment_status="succeeded",
        status="paid",
        provider="khipu",
        user_id=88,
        email="client@example.com",
        firenze_client_id=None,
        shipping_email="client@example.com",
        shipping_name="Cliente Test",
        shipping_phone="56911112222",
        transaction_id="txn_101",
        user=None,
        items=[
            SimpleNamespace(
                item_type="minute_pack",
                item_id=7,
                quantity=2,
            ),
        ],
        firenze_payload={},
        firenze_response={},
    )
    pack = SimpleNamespace(id=7, minutes=10)

    def fake_get(model, model_id):
        if model is signals.Order:
            return order
        if model is signals.MinutePack:
            return pack
        return None

    monkeypatch.setattr(signals.db.session, "get", fake_get)
    monkeypatch.setattr(signals.db.session, "commit", lambda: calls.__setitem__("committed", True))
    monkeypatch.setattr(signals, "search_client", lambda **kwargs: 555)
    monkeypatch.setattr(
        signals,
        "post_purchase",
        lambda **kwargs: calls.__setitem__("post_kwargs", kwargs) or {"client_id": 555, "ok": True},
    )
    monkeypatch.setattr(signals, "send_telegram_notification", lambda message: None)
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_success_notification",
        lambda order: calls.__setitem__("success_telegram", order.id),
    )
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_admin_email",
        lambda order, audit_rows: calls.__setitem__("admin_email", order.id),
    )

    ok = signals.post_purchase_process(order_id=101)

    assert ok is True
    assert order.firenze_client_id == 555
    assert calls["post_kwargs"]["segundos"] == 1200
    assert calls["post_kwargs"]["client_id"] == 555
    assert calls["post_kwargs"]["ani"] == "56911112222"
    assert order.firenze_payload == [calls["post_kwargs"]]
    assert order.firenze_response == [{"client_id": 555, "ok": True}]
    assert order.status == signals.OrderStatus.DELIVERED
    assert calls["success_telegram"] == 101
    assert calls["admin_email"] == 101
    assert calls.get("committed") is True


def test_post_purchase_process_warns_on_client_id_mismatch(monkeypatch):
    calls: dict[str, str] = {}
    order = SimpleNamespace(
        id=202,
        payment_status="succeeded",
        status="paid",
        provider="khipu",
        user_id=88,
        email="client@example.com",
        firenze_client_id=300,
        shipping_email="client@example.com",
        shipping_name="Cliente Test",
        shipping_phone="56933334444",
        transaction_id="txn_202",
        user=None,
        items=[
            SimpleNamespace(
                item_type="minute_pack",
                item_id=9,
                quantity=1,
            ),
        ],
        firenze_payload={},
        firenze_response={},
    )
    pack = SimpleNamespace(id=9, minutes=5)

    def fake_get(model, model_id):
        if model is signals.Order:
            return order
        if model is signals.MinutePack:
            return pack
        return None

    monkeypatch.setattr(signals.db.session, "get", fake_get)
    monkeypatch.setattr(signals.db.session, "commit", lambda: None)
    monkeypatch.setattr(signals, "post_purchase", lambda **kwargs: {"client_id": 999, "ok": True})
    monkeypatch.setattr(
        signals,
        "send_telegram_notification",
        lambda message: calls.__setitem__("message", message),
    )
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_success_notification",
        lambda order: calls.__setitem__("success_telegram", order.id),
    )
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_admin_email",
        lambda order, audit_rows: calls.__setitem__("admin_email", order.id),
    )

    ok = signals.post_purchase_process(order_id=202)

    assert ok is True
    assert order.firenze_payload == [
        {
            "client_id": 300,
            "segundos": 300,
            "transaction_id": "txn_202",
            "name": "Cliente Test",
            "email": "client@example.com",
            "ani": "56933334444",
        }
    ]
    assert order.firenze_response == [{"client_id": 999, "ok": True}]
    assert "Clientid distinto" in calls["message"]
    assert calls["success_telegram"] == 202
    assert calls["admin_email"] == 202
    assert order.status == signals.OrderStatus.DELIVERED


def test_post_purchase_process_ignores_non_succeeded_order(monkeypatch):
    order = SimpleNamespace(
        id=303,
        payment_status="pending",
    )
    called = {"post": False, "commit": False}

    monkeypatch.setattr(
        signals.db.session,
        "get",
        lambda model, model_id: order if model is signals.Order else None,
    )
    monkeypatch.setattr(signals.db.session, "commit", lambda: called.__setitem__("commit", True))
    monkeypatch.setattr(signals, "post_purchase", lambda **kwargs: called.__setitem__("post", True))

    ok = signals.post_purchase_process(order_id=303)

    assert ok is False
    assert called == {"post": False, "commit": False}


def test_associate_order_user_by_email_links_user(monkeypatch):
    order = SimpleNamespace(id=404, user_id=None, email="Found@Example.com")
    fake_user = SimpleNamespace(id=77)

    class _FakeUserQuery:
        def filter_by(self, **kwargs):
            assert kwargs == {"email": "found@example.com"}
            return self

        def first(self):
            return fake_user

    monkeypatch.setattr(
        signals,
        "User",
        SimpleNamespace(query=_FakeUserQuery()),
    )

    signals._associate_order_user_by_email(order)

    assert order.user_id == 77


def test_post_purchase_process_stops_and_notifies_when_post_returns_none(monkeypatch):
    calls: dict[str, object] = {}
    order = SimpleNamespace(
        id=505,
        payment_status="succeeded",
        status="paid",
        provider="khipu",
        user_id=None,
        email="client@example.com",
        firenze_client_id=123,
        shipping_email="client@example.com",
        shipping_name="Cliente Test",
        shipping_phone="56955556666",
        transaction_id="txn_505",
        user=None,
        items=[SimpleNamespace(item_type="minute_pack", item_id=11, quantity=1)],
        firenze_payload={},
        firenze_response={},
    )
    pack = SimpleNamespace(id=11, minutes=5)

    def fake_get(model, model_id):
        if model is signals.Order:
            return order
        if model is signals.MinutePack:
            return pack
        return None

    monkeypatch.setattr(signals.db.session, "get", fake_get)
    monkeypatch.setattr(
        signals.db.session,
        "commit",
        lambda: calls.__setitem__("committed", calls.get("committed", 0) + 1),
    )
    monkeypatch.setattr(signals, "post_purchase", lambda **kwargs: None)
    monkeypatch.setattr(
        signals,
        "send_telegram_notification",
        lambda message: calls.__setitem__("telegram", message),
    )
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_success_notification",
        lambda order: calls.__setitem__("success_telegram", order.id),
    )
    monkeypatch.setattr(
        signals,
        "_send_post_purchase_admin_email",
        lambda order, audit_rows: calls.__setitem__("admin_email", order.id),
    )

    ok = signals.post_purchase_process(order_id=505)

    assert ok is False
    assert "post_purchase returned None" in calls["telegram"]
    assert order.firenze_payload == [
        {
            "client_id": 123,
            "segundos": 300,
            "transaction_id": "txn_505",
            "name": "Cliente Test",
            "email": "client@example.com",
            "ani": "56955556666",
        }
    ]
    assert order.firenze_response == [None]
    assert order.status == "paid"
    assert "success_telegram" not in calls
    assert "admin_email" not in calls
