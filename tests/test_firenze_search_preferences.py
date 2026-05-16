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
