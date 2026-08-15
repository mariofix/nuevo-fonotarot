from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from flask import url_for

from nuevo_fonotarot.extensions import db, user_datastore
from nuevo_fonotarot.flask_app import create_flask


# Need to import models *after* the app is created to avoid the FsModels error,
# because set_db_info is called in create_flask
@pytest.fixture(scope="session")
def app():
    app = create_flask("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@patch("nuevo_fonotarot.api.api.search_client")
@patch("nuevo_fonotarot.api.api._complete_promo_claim")
@patch("nuevo_fonotarot.api.api._send_admin_promo_notification")
@patch("nuevo_fonotarot.api.api._promo_claim_remaining")
def test_promo_cobrar_success(mock_claim, mock_send, mock_complete, mock_search, client, app):
    from nuevo_fonotarot.models import SiteSettings

    mock_search.return_value = None  # Client not found, eligible
    mock_claim.return_value = (True, 4)
    mock_complete.return_value = ({"success": True, "client_id": 1234, "created": True}, 200)

    with app.test_request_context():
        # Make sure stock exists
        setting = SiteSettings(key="promo_free_minutes_remaining", value="5")
        db.session.add(setting)
        db.session.commit()

        # Test promo cobrar
        response = client.post("/api/v1/promo/cobrar", json={"ani": "56912345678"})

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        assert "redirect" in data

        # Ensure counter was decremented (we mock _promo_claim_remaining, so it's not decremented in DB in tests)

        # Verify session values using flask.session
        with client.session_transaction() as sess:
            assert sess.get("promo_ani") == "56912345678"
            assert sess.get("promo_client_id") == 1234
            assert sess.get("promo_remaining") == 4


def test_promo_cobrar_invalid_phone(client, app):
    response = client.post("/api/v1/promo/cobrar", json={"ani": "invalid_phone"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_phone"


@patch("nuevo_fonotarot.api.api._finalize_promo_email")
def test_promo_actualizar_email_success(mock_finalize, client, app):
    mock_finalize.return_value = ({"success": True, "redirect": "/profile"}, 200)

    # Must have promo_ani in session
    with client.session_transaction() as sess:
        sess["promo_ani"] = "56912345678"
        sess["promo_client_id"] = 1234

    response = client.post("/api/v1/promo/actualizar-email", json={"email": "test@example.com"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    mock_finalize.assert_called_once_with("test@example.com")


def test_promo_actualizar_email_no_session(client, app):
    response = client.post("/api/v1/promo/actualizar-email", json={"email": "test@example.com"})
    assert response.status_code == 401
    assert response.get_json()["error"] == "session_expired"


def test_promo_actualizar_email_invalid_email(client, app):
    with client.session_transaction() as sess:
        sess["promo_ani"] = "56912345678"

    response = client.post("/api/v1/promo/actualizar-email", json={"email": "invalid-email"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_email"


def test_auto_discount_matches_role_and_recent_spend(app):
    from nuevo_fonotarot.models import DiscountCode, Order, Role
    from nuevo_fonotarot.tienda.utils import find_auto_discount_code_for_user

    with app.app_context():
        from nuevo_fonotarot.models import User

        role = user_datastore.find_role("vip-customer") or Role(name="vip-customer")
        db.session.add(role)

        user = User(email="vip@example.com", username="56987654321", active=True)
        user.password = "test-password-123"
        user.roles.append(role)
        db.session.add(user)

        discount = DiscountCode(
            code="VIP10",
            discount_type="percentage",
            discount_value=Decimal("10"),
            currency="CLP",
            is_active=True,
            auto_apply=True,
            auto_apply_criteria={"roles": ["vip-customer"], "match_mode": "any"},
        )
        db.session.add(discount)

        order = Order(
            user_id=user.id,
            amount=Decimal("15000"),
            currency="CLP",
            email=user.email,
            provider="flow",
            payment_status="succeeded",
            status="paid",
            created_at=datetime.now() - timedelta(days=5),
        )
        db.session.add(order)
        db.session.commit()

        assert discount.matches_user(user) is True
        assert find_auto_discount_code_for_user(user, Decimal("12000"), "CLP") == discount

        spend_discount = DiscountCode(
            code="SPEND15",
            discount_type="fixed",
            discount_value=Decimal("1500"),
            currency="CLP",
            is_active=True,
            auto_apply=True,
            auto_apply_criteria={"min_recent_spend": "10000", "recent_spend_window_days": 30, "match_mode": "all"},
        )
        db.session.add(spend_discount)
        db.session.commit()

        assert spend_discount.matches_user(user) is True
        assert find_auto_discount_code_for_user(user, Decimal("20000"), "CLP").code == "VIP10"

        non_vip_user = User(email="regular@example.com", username="56912345678", active=True)
        non_vip_user.password = "test-password-123"
        db.session.add(non_vip_user)
        db.session.commit()

        order = Order(
            user_id=non_vip_user.id,
            amount=Decimal("20000"),
            currency="CLP",
            email=non_vip_user.email,
            provider="flow",
            payment_status="succeeded",
            status="paid",
            created_at=datetime.now() - timedelta(days=10),
        )
        db.session.add(order)
        db.session.commit()

        assert spend_discount.matches_user(non_vip_user) is True
        assert find_auto_discount_code_for_user(non_vip_user, Decimal("20000"), "CLP").code == "SPEND15"
