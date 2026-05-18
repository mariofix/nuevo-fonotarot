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

from nuevo_fonotarot import actions
from nuevo_fonotarot.tienda.pagos import views as pagos_views


def test_process_user_registration_prefers_username_phone(monkeypatch):
    captured: dict[str, str | None] = {"phone": None}

    def fake_search_client(*, email, phone):
        captured["phone"] = phone
        return None

    monkeypatch.setattr(actions, "search_client", fake_search_client)
    monkeypatch.setattr(actions, "notify_new_user_registration", lambda **kwargs: None)

    user = SimpleNamespace(
        id=10,
        email="user@example.com",
        username="56911112222",
        phone="56900000000",
        firenze_client_id=None,
        roles=[],
    )

    found = actions.process_user_registration(user)

    assert found is False
    assert captured["phone"] == "56911112222"


def test_sync_firenze_on_payment_uses_username_for_ani(monkeypatch):
    captured: dict[str, str | None] = {"ani": None}

    def fake_create_client(*, name, email, ani, transaction_id):
        captured["ani"] = ani
        return 321

    monkeypatch.setattr("nuevo_fonotarot.firenze.create_client", fake_create_client)

    order = SimpleNamespace(
        id=77,
        firenze_client_id=None,
        shipping_name="Demo User",
        shipping_email="demo@example.com",
        shipping_phone="56999998888",
        transaction_id="txn_1",
        user=SimpleNamespace(username="56912345678"),
        user_id=None,
    )

    ok = pagos_views._sync_firenze_on_payment(order)

    assert ok is True
    assert order.firenze_client_id == 321
    assert captured["ani"] == "56912345678"


def test_sync_firenze_on_payment_falls_back_to_shipping_phone(monkeypatch):
    captured: dict[str, str | None] = {"ani": None}

    def fake_create_client(*, name, email, ani, transaction_id):
        captured["ani"] = ani
        return 654

    monkeypatch.setattr("nuevo_fonotarot.firenze.create_client", fake_create_client)

    order = SimpleNamespace(
        id=78,
        firenze_client_id=None,
        shipping_name="Anon",
        shipping_email="anon@example.com",
        shipping_phone="56977776666",
        transaction_id="txn_2",
        user=None,
        user_id=None,
    )

    ok = pagos_views._sync_firenze_on_payment(order)

    assert ok is True
    assert order.firenze_client_id == 654
    assert captured["ani"] == "56977776666"
