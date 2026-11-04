import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smdx_api.config import AppConfig
from smdx_api.main import create_app
from smdx_api.security import is_csrf_safe


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_state_changing_without_header_is_unsafe(method):
    assert is_csrf_safe(method, {}) is False
    assert is_csrf_safe(method, {"X-Requested-With": "other"}) is False
    assert is_csrf_safe(method, {"X-Requested-With": "smdx"}) is True


def test_get_is_always_safe():
    assert is_csrf_safe("GET", {}) is True


def test_post_without_header_returns_403(app):
    @app.post("/_t")
    def _t():
        return {"ok": True}

    raw = TestClient(app)  # 既定ヘッダなし
    res = raw.post("/_t")
    assert res.status_code == 403
    assert res.json() == {"detail": "この操作を行う権限がありません"}
    assert raw.post("/_t", headers={"X-Requested-With": "smdx"}).status_code == 200


def test_login_without_header_is_rejected(app):
    assert TestClient(app).post("/api/auth/login", json={}).status_code == 403


def test_cors_allows_configured_origin(client):
    res = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Requested-With",
        },
    )
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert res.headers["access-control-allow-credentials"] == "true"


def _add_session_routes(app):
    @app.post("/_login")
    def _login(request: Request):
        request.session["user_id"] = 1
        return {}

    @app.get("/_touch")
    def _touch(request: Request):
        return {"user_id": request.session.get("user_id")}


def test_session_max_age_default_and_sliding(app):
    _add_session_routes(app)
    c = TestClient(app, headers={"X-Requested-With": "smdx"})
    first = c.post("/_login")
    assert "max-age=10800" in first.headers["set-cookie"].lower()  # 既定3時間
    again = c.get("/_touch")  # 操作のたびに出し直す(期限が延びる)
    assert again.json() == {"user_id": 1}
    assert "max-age=10800" in again.headers["set-cookie"].lower()


def test_session_max_age_from_config(config):
    app = create_app(config.model_copy(update={"session_max_age_hours": 0.5}))
    _add_session_routes(app)
    res = TestClient(app, headers={"X-Requested-With": "smdx"}).post("/_login")
    assert "max-age=1800" in res.headers["set-cookie"].lower()


def test_session_max_age_must_be_positive(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_MAX_AGE_HOURS", "0")
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None)


def _post_import(client, size):
    return client.post("/api/imports/pos", files={"file": ("pos.csv", b"x" * size, "text/csv")},
                       data={"department_code": "VEG"})


def test_import_size_is_checked_before_reading_body(make_client):
    """上限を大きく超える取込は、本文を読む前(ログインの確認より前)に 413 で拒否する。"""
    client = make_client(import_max_mb=0.01)
    res = _post_import(client, 200 * 1024)
    assert res.status_code == 413
    assert res.json()["detail"] == "ファイルが大きすぎます(上限 0.01MB)。期間を分けて取り込んでください"
    # 上限+multipart の見出しの分までは通し、ログインの確認に進む
    assert _post_import(client, 1024).status_code == 401


def test_import_without_content_length_is_411():
    import asyncio

    from smdx_api.security import ImportSizeMiddleware

    reached, sent = [], []

    async def app(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    mw = ImportSizeMiddleware(app, max_mb=1)
    scope = {"type": "http", "method": "POST", "path": "/api/imports/pos", "headers": [], "query_string": b""}
    asyncio.run(mw(scope, receive, send))
    assert reached == [] and sent[0]["status"] == 411
    # 取込以外の要求はそのまま通す
    asyncio.run(mw({**scope, "path": "/api/inventory"}, receive, send))
    assert reached == ["/api/inventory"]
