from types import SimpleNamespace

from flask import Flask
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
        "sender": app,
        "weak": False,
    }


def test_handle_khipu_webhook_event_completes_succeeded_order(monkeypatch):
    order = SimpleNamespace(id=42, status=OrderStatus.PENDING, firenze_client_id=None)
    captured: dict[str, object] = {}

    monkeypatch.setattr(pagos_views, "_find_order_by_payment_id", lambda payment_id: order)
    monkeypatch.setattr(pagos_views.db.session, "commit", lambda: None)
    monkeypatch.setattr(
        pagos_views,
        "_complete_succeeded_order_admin_flow",
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


def test_handle_payment_webhook_finished_accepts_signal_sender(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        pagos_views,
        "_handle_payment_webhook_event",
        lambda event: captured.update(event=event),
    )
    event = SimpleNamespace(
        payment_id="sig_1",
        provider="khipu",
        state=SimpleNamespace(value="succeeded"),
        event_type="payment.conciliated",
    )

    pagos_views._handle_payment_webhook_finished(object(), event=event)

    assert captured == {"event": event}


def test_handle_flow_webhook_event_syncs_then_completes(monkeypatch):
    order = SimpleNamespace(id=43, status=OrderStatus.PENDING, payment_status="pending")
    captured: dict[str, object] = {}

    def fake_sync_from_provider():
        order.payment_status = "succeeded"

    monkeypatch.setattr(pagos_views, "_find_order_by_payment_id", lambda payment_id: order)
    monkeypatch.setattr(pagos_views.db.session, "commit", lambda: None)
    monkeypatch.setattr(order, "sync_from_provider", fake_sync_from_provider, raising=False)
    monkeypatch.setattr(
        pagos_views,
        "_complete_succeeded_order_admin_flow",
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
        "_complete_succeeded_order_admin_flow",
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


def test_complete_succeeded_order_admin_flow_keeps_pending_if_firenze_fails(monkeypatch):
    order = SimpleNamespace(id=45, status=OrderStatus.PENDING, firenze_client_id=None)
    captured: dict[str, int] = {"confirm": 0, "failure": 0, "commits": 0}

    monkeypatch.setattr(pagos_views, "_sync_firenze_on_payment", lambda found_order: False)
    monkeypatch.setattr(
        pagos_views,
        "_send_order_confirmation_email",
        lambda found_order: captured.__setitem__("confirm", captured["confirm"] + 1),
    )
    monkeypatch.setattr(
        pagos_views,
        "_send_firenze_failure_email",
        lambda found_order: captured.__setitem__("failure", captured["failure"] + 1),
    )
    monkeypatch.setattr(
        pagos_views.db.session,
        "commit",
        lambda: captured.__setitem__("commits", captured["commits"] + 1),
    )

    completed = pagos_views._complete_succeeded_order_admin_flow(order, "webhook-khipu")

    assert completed is False
    assert order.status == OrderStatus.PENDING
    assert captured == {"confirm": 0, "failure": 1, "commits": 0}


def test_send_order_confirmation_email_respects_purchase_notifications(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        DALEKS_URL="https://daleks.example",
        DALEKS_TIMEOUT=10,
        DALEKS_SMTP_ACCOUNT="smtp-account",
        SECURITY_EMAIL_SENDER="hola@fonotarot.cl",
        SITE_URL="https://fonotarot.example",
    )
    sent_to: list[str] = []

    class FakeDaleksClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_email(self, *, to, **kwargs):
            sent_to.extend(to)

    admin_role = SimpleNamespace(
        users=SimpleNamespace(
            all=lambda: [SimpleNamespace(active=True, email="admin@example.com")]
        )
    )
    order = SimpleNamespace(
        id=46,
        shipping_email="client@example.com",
        shipping_name="Clienta",
        provider="khipu",
        total_display="$9.990",
        items=[],
        user=SimpleNamespace(notification_preferences=[]),
    )

    monkeypatch.setattr(pagos_views, "render_template", lambda *args, **kwargs: "html")
    monkeypatch.setattr(
        "nuevo_fonotarot.models.Role",
        SimpleNamespace(query=SimpleNamespace(filter_by=lambda **kwargs: SimpleNamespace(first=lambda: admin_role))),
        raising=False,
    )
    monkeypatch.setattr("daleks.contrib.client.DaleksClient", FakeDaleksClient, raising=False)

    with app.app_context():
        pagos_views._send_order_confirmation_email(order)

    assert sent_to == ["admin@example.com"]
