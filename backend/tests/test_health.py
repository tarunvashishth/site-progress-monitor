from fastapi.testclient import TestClient

from cpm.api.main import app


def test_healthz():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_cors_allows_each_listed_origin_and_nothing_else(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from cpm.api import main
    from cpm.core.config import get_settings

    monkeypatch.setenv("WEB_ORIGIN", "https://a.example, https://b.example")
    get_settings.cache_clear()
    app = importlib.reload(main).app
    c = TestClient(app)

    def allowed(origin):
        r = c.options(
            "/healthz", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
        )
        return r.headers.get("access-control-allow-origin")

    assert allowed("https://a.example") == "https://a.example"
    assert allowed("https://b.example") == "https://b.example"
    assert allowed("https://evil.example") is None
