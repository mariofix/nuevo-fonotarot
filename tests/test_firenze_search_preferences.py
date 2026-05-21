from nuevo_fonotarot import firenze


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


def test_search_client_minutes_prefers_client_id_over_email(monkeypatch):
    captured: dict[str, dict] = {"params": {}}

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        return _FakeResponse({"found": True, "minutes": 17})

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "k", "x-api-secret": "s"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)
    monkeypatch.setattr(firenze.requests, "get", fake_get)

    minutes, error = firenze.search_client_minutes(client_id=123, email="fallback@example.com")

    assert error is None
    assert minutes == 17
    assert captured["params"]["client_id"] == 123
    assert "email" not in captured["params"]


def test_search_client_minutes_falls_back_to_email(monkeypatch):
    captured: dict[str, dict] = {"params": {}}

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        return _FakeResponse({"found": True, "minutes": 9})

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "k", "x-api-secret": "s"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)
    monkeypatch.setattr(firenze.requests, "get", fake_get)

    minutes, error = firenze.search_client_minutes(client_id=None, email="user@example.com")

    assert error is None
    assert minutes == 9
    assert captured["params"]["email"] == "user@example.com"
    assert "client_id" not in captured["params"]


def test_list_client_anis_uses_new_nested_endpoint(monkeypatch):
    captured: dict[str, object] = {}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse({"ok": True, "service": "fonotarot-cl", "client_id": 123, "anis": ["56912345678", "56987654321"]})

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "k", "x-api-secret": "s"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)
    monkeypatch.setattr(firenze.requests, "get", fake_get)

    anis = firenze.list_client_anis(123)

    assert anis == ["56912345678", "56987654321"]
    assert captured["url"] == "http://firenze.local/api/v1/clients/fonotarot-cl/123/ani"
    assert captured["headers"] == {"x-api-key": "k", "x-api-secret": "s"}
    assert captured["timeout"] == 5


def test_add_client_ani_posts_minimal_body_to_nested_endpoint(monkeypatch):
    captured: dict[str, object] = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse({"ok": True, "service": "fonotarot-cl", "client_id": 123, "ani": "56912345678", "created": True})

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "k", "x-api-secret": "s"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)
    monkeypatch.setattr(firenze.requests, "post", fake_post)

    success, created = firenze.add_client_ani(123, "+56 9 1234 5678")

    assert success is True
    assert created is True
    assert captured["url"] == "http://firenze.local/api/v1/clients/fonotarot-cl/123/ani"
    assert captured["json"] == {"ani": "56912345678"}
    assert captured["headers"] == {"x-api-key": "k", "x-api-secret": "s"}
    assert captured["timeout"] == 5


def test_delete_client_ani_uses_new_nested_endpoint(monkeypatch):
    captured: dict[str, object] = {}

    def fake_delete(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse({"ok": True, "service": "fonotarot-cl", "client_id": 123, "ani": "56912345678", "deleted": True})

    monkeypatch.setattr(firenze, "_auth_headers", lambda: {"x-api-key": "k", "x-api-secret": "s"})
    monkeypatch.setattr(firenze, "_base_url", lambda: "http://firenze.local")
    monkeypatch.setattr(firenze, "_timeout", lambda: 5)
    monkeypatch.setattr(firenze.requests, "delete", fake_delete)

    success, deleted = firenze.delete_client_ani(123, "+56 9 1234 5678")

    assert success is True
    assert deleted is True
    assert captured["url"] == "http://firenze.local/api/v1/clients/fonotarot-cl/123/ani/56912345678"
    assert captured["headers"] == {"x-api-key": "k", "x-api-secret": "s"}
    assert captured["timeout"] == 5
