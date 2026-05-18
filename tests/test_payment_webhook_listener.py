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

from nuevo_fonotarot import flask_app
from nuevo_fonotarot.models import OrderStatus
from nuevo_fonotarot.tienda.pagos import views as pagos_views


def test_init_merchants_registers_payment_webhook_listener(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(flask_app.merchants_ext, "init_app", lambda *args, **kwargs: None)
    monkeypatch.setattr(flask_app.webhook_event_finished, "connect", lambda receiver, sender=None, weak=True: captured.update(receiver=receiver, sender=sender, weak=weak))

    app = SimpleNamespace(config={"KHIPU_API_KEY": "", "FLOW_API_KEY": ""})
    flask_app._init_merchants(app, admin=None)

    assert captured == {
        "receiver": pagos_views._handle_payment_webhook_finished,
        "sender": flask_app.merchants_ext,
        "weak": False,
    }


def test_handle_khipu_webhook_event_completes_succeeded_order(monkeypatch):
    order = SimpleNamespace(id=42, status=OrderStatus.PENDING, firenze_client_id=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(pagos_views, "_find_order_by_payment_id", lambda payment_id: order)
    monkeypatch.setattr(pagos_views.db.session, "commit", lambda: None)
    monkeypatch.setattr(
        pagos_views,
        "_complete_succeeded_order",
        lambda found_order, label: captured.update(order=found_order, label=label),
    )

    event = SimpleNamespace(
        payment_id="zbqvfebaorme",
        provider="khipu",
        state=SimpleNamespace(value="succeeded"),
        event_type="payment.conciliated",
    )

    pagos_views._handle_khipu_webhook_event(event)

    assert captured == {"order": order, "label": "webhook-khipu"}


def test_handle_flow_webhook_event_syncs_then_completes(monkeypatch):
    order = SimpleNamespace(id=43, status=OrderStatus.PENDING, state="pending")
    captured: dict[str, object] = {}

    def fake_sync_from_provider():
        order.state = "succeeded"

    monkeypatch.setattr(pagos_views, "_find_order_by_payment_id", lambda payment_id: order)
    monkeypatch.setattr(pagos_views.db.session, "commit", lambda: None)
    monkeypatch.setattr(order, "sync_from_provider", fake_sync_from_provider, raising=False)
    monkeypatch.setattr(
        pagos_views,
        "_complete_succeeded_order",
        lambda found_order, label: captured.update(order=found_order, label=label),
    )

    event = SimpleNamespace(
        payment_id="flow-token",
        provider="flow",
        state=SimpleNamespace(value="unknown"),
        event_type="payment.notification",
    )

    pagos_views._handle_flow_webhook_event(event)

    assert captured == {"order": order, "label": "webhook-flow"}


def test_handle_stripe_webhook_event_completes_succeeded_order(monkeypatch):
    order = SimpleNamespace(id=44, status=OrderStatus.PENDING, firenze_client_id=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(pagos_views, "_find_order_by_payment_id", lambda payment_id: order)
    monkeypatch.setattr(pagos_views.db.session, "commit", lambda: None)
    monkeypatch.setattr(
        pagos_views,
        "_complete_succeeded_order",
        lambda found_order, label: captured.update(order=found_order, label=label),
    )

    event = SimpleNamespace(
        payment_id="pi_123",
        provider="stripe",
        state=SimpleNamespace(value="succeeded"),
        event_type="checkout.session.completed",
    )

    pagos_views._handle_stripe_webhook_event(event)

    assert captured == {"order": order, "label": "webhook-stripe"}
