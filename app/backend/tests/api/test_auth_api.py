import pytest
from fastapi import HTTPException

from smdx_api.api.deps import department_for
from smdx_api.auth.permissions import Principal


def test_me_requires_login(client):
    res = client.get("/api/me")
    assert res.status_code == 401
    assert res.json()["detail"] == "ログインしてください"


def test_login_body_is_validated(client):
    assert client.post("/api/auth/login", json={"login_id": "a"}).status_code == 422


def test_login_password_has_max_length(client):
    # 極端に長いパスワードで argon2 の計算をさせない(PR #1 指摘6)
    assert client.post("/api/auth/login", json={"login_id": "a", "password": "x" * 257}).status_code == 422


@pytest.mark.db
def test_login_me_logout(client, user_factory):
    u = user_factory(role="staff", departments=("VEG", "DELI"))
    res = client.post("/api/auth/login", json={"login_id": u.login_id, "password": "pass1234"})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    me = client.get("/api/me").json()
    assert me["role"] == "staff"
    assert {d["code"] for d in me["departments"]} == {"VEG", "DELI"}
    assert [d["code"] for d in me["accessible_departments"]] == ["DELI", "VEG"]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


@pytest.mark.db
def test_manager_accessible_departments_are_all(client, user_factory, login):
    login(client, user_factory(role="manager", departments=()))
    me = client.get("/api/me").json()
    assert me["departments"] == []
    assert [d["code"] for d in me["accessible_departments"]] == ["DELI", "FISH", "VEG"]


@pytest.mark.db
@pytest.mark.parametrize("login_id,password,active", [
    ("u1", "bad", True), ("nobody", "pass1234", True), ("u1", "pass1234", False),
])
def test_login_failure_same_message(client, user_factory, login_id, password, active):
    user_factory(login_id="u1", is_active=active)
    res = client.post("/api/auth/login", json={"login_id": login_id, "password": password})
    assert res.status_code == 401
    assert res.json()["detail"] == "ログインIDまたはパスワードが正しくありません。"


@pytest.mark.db
def test_deactivated_user_session_is_rejected(client, user_factory, login, db):
    u = user_factory()
    login(client, u)
    u.is_active = False
    db.flush()
    assert client.get("/api/me").status_code == 401


@pytest.mark.db
def test_secure_cookie_when_configured(user_factory, make_client):
    c = make_client(session_cookie_secure=True)
    u = user_factory()
    res = c.post("/api/auth/login", json={"login_id": u.login_id, "password": "pass1234"})
    assert "secure" in res.headers["set-cookie"].lower()


@pytest.mark.db
@pytest.mark.parametrize("code,status", [("FISH", 403), ("veg", 404), ("NONE", 404)])
def test_department_for_rejects_other_and_unknown(db, code, status):
    staff = Principal(1, "a", "staff", frozenset({"VEG"}))
    with pytest.raises(HTTPException) as e:
        department_for(code, staff, db)
    assert e.value.status_code == status


@pytest.mark.db
def test_department_for_returns_own(db):
    assert department_for("VEG", Principal(1, "a", "staff", frozenset({"VEG"})), db).code == "VEG"


def _login(client, login_id, password):
    return client.post("/api/auth/login", json={"login_id": login_id, "password": password})


@pytest.mark.db
def test_login_locks_after_consecutive_failures(client, user_factory, fixed_now, db):
    """同じログインIDで5回続けて失敗すると15分ロックし、その間は正しいパスワードでも同じ 401 の文言にする。"""
    u = user_factory()
    for _ in range(4):
        assert _login(client, u.login_id, "wrong").status_code == 401
    assert _login(client, u.login_id, "pass1234").status_code == 200   # 4回までなら成功し、回数を0に戻す
    db.refresh(u)
    assert (u.failed_login_count, u.locked_until) == (0, None)
    for _ in range(5):
        assert _login(client, u.login_id, "wrong").status_code == 401
    res = _login(client, u.login_id, "pass1234")
    assert res.status_code == 401 and res.json()["detail"] == "ログインIDまたはパスワードが正しくありません。"
    fixed_now.advance(minutes=14, seconds=59)
    assert _login(client, u.login_id, "pass1234").status_code == 401
    fixed_now.advance(seconds=1)
    assert _login(client, u.login_id, "pass1234").status_code == 200


@pytest.mark.db
def test_login_lock_limits_follow_config(make_client, user_factory, fixed_now):
    client = make_client(login_max_failures=2, login_lock_minutes=1)
    u = user_factory()
    for _ in range(2):
        _login(client, u.login_id, "wrong")
    assert _login(client, u.login_id, "pass1234").status_code == 401
    fixed_now.advance(minutes=1)
    assert _login(client, u.login_id, "pass1234").status_code == 200


@pytest.mark.db
def test_login_unknown_id_is_plain_failure(client, fixed_now, db):
    for _ in range(6):
        res = _login(client, "nobody", "wrong")
        assert res.status_code == 401 and res.json()["detail"] == "ログインIDまたはパスワードが正しくありません。"


@pytest.mark.parametrize("enabled,status", [(True, 200), (False, 404)])
def test_api_docs_can_be_disabled(make_client, enabled, status):
    client = make_client(api_docs_enabled=enabled)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == status, path
