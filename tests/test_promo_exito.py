from types import SimpleNamespace

from nuevo_fonotarot import create_flask, firenze

_TEST_APP = None


def _make_testing_app(monkeypatch):
    global _TEST_APP
    if _TEST_APP is not None:
        return _TEST_APP

    from flask_security.models import fsqla_v3 as fsqla

    original_set_db_info = fsqla.FsModels.set_db_info

    def safe_set_db_info(*args, **kwargs):
        try:
            return original_set_db_info(*args, **kwargs)
        except Exception as exc:
            if "already defined for this MetaData instance" in str(exc):
                return None
            raise

    monkeypatch.setattr(fsqla.FsModels, "set_db_info", safe_set_db_info)
    _TEST_APP = create_flask("testing")
    return _TEST_APP


def test_complete_promo_credit_posts_expected_payload(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "key", "x-api-secret": "secret"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"client_id": 987}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(firenze.requests, "post", fake_post)

    client_id = firenze.complete_promo_credit("56912345678", 300)

    assert client_id == 987
    assert captured["url"] == "http://firenze.local/api/v1/payments/complete"
    assert captured["headers"] == {"x-api-key": "key", "x-api-secret": "secret"}
    assert captured["timeout"] == 5
    assert captured["json"] == {
        "service": "fonotarot-cl",
        "credits": 300,
        "ani": "56912345678",
        "transaction_id": "pr_56912345678",
    }
    assert "client_id" not in captured["json"]


def test_api_promo_cobrar_completes_claim_and_stores_session(monkeypatch):
    app = _make_testing_app(monkeypatch)

    search_calls: list[str] = []
    monkeypatch.setattr(
        "nuevo_fonotarot.content.views.search_client", lambda **kwargs: search_calls.append(kwargs["ani"]) or None
    )
    monkeypatch.setattr("nuevo_fonotarot.content.views._promo_claim_remaining", lambda: (True, 35))
    monkeypatch.setattr("nuevo_fonotarot.content.views.complete_promo_credit", lambda ani, credits: 987)
    monkeypatch.setattr("nuevo_fonotarot.content.views._send_admin_promo_notification", lambda *args, **kwargs: None)

    with app.test_client() as client:
        response = client.post("/api/promo/cobrar", json={"ani": "56912345678"})
        with client.session_transaction() as sess:
            assert sess["promo_ani"] == "56912345678"
            assert sess["promo_remaining"] == 35
            assert sess["promo_client_id"] == 987
            assert sess.get("promo_completed") is None

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "redirect": "/promo/exito"}
    assert search_calls == ["56912345678"]


def test_api_promo_cobrar_rejects_existing_ani(monkeypatch):
    app = _make_testing_app(monkeypatch)
    monkeypatch.setattr("nuevo_fonotarot.content.views.search_client", lambda **kwargs: 123)

    with app.test_client() as client:
        response = client.post("/api/promo/cobrar", json={"ani": "56912345678"})

    assert response.status_code == 409
    assert response.get_json()["error"] == "not_eligible"


def test_promo_exito_posts_email_creates_account_and_logs_in(monkeypatch):
    app = _make_testing_app(monkeypatch)
    user = SimpleNamespace(
        id=12,
        email="user@example.com",
        username="56912345678",
        phone="56912345678",
        firenze_client_id=987,
        roles=[],
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("nuevo_fonotarot.content.views.register_checkout_account", lambda email, phone: (user, True))
    monkeypatch.setattr("nuevo_fonotarot.content.views.process_user_registration", lambda registered_user: True)

    def fake_update_client_profile(client_id, **kwargs):
        captured["client_id"] = client_id
        captured["kwargs"] = kwargs
        return True

    def fake_login_user(registered_user, remember=False, authn_via=None):
        captured["login_user"] = registered_user
        captured["remember"] = remember
        captured["authn_via"] = authn_via
        return True

    monkeypatch.setattr("nuevo_fonotarot.content.views.update_client_profile", fake_update_client_profile)
    monkeypatch.setattr("nuevo_fonotarot.content.views.login_user", fake_login_user)
    monkeypatch.setattr("nuevo_fonotarot.content.views._send_user_promo_instructions", lambda email, remaining: True)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["promo_ani"] = "56912345678"
            sess["promo_client_id"] = 987
            sess["promo_remaining"] = 35

        response = client.post("/promo/exito", json={"email": "User@Example.com"})

    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "success": True,
        "created": True,
        "client_id": 987,
        "authenticated": True,
        "email_sent": True,
        "redirect": body["redirect"],
    }
    assert body["redirect"].endswith("/profile")
    assert captured["client_id"] == 987
    assert captured["kwargs"] == {"email": "user@example.com"}
    assert captured["login_user"] is user
    assert captured["remember"] is False
    assert captured["authn_via"] == ["promo"]
