"""惣菜の陳列残数の入力(PUT /api/production/display-stock。詳細設計書「API仕様」「発注数・製造数の計算(惣菜)」)。"""
from datetime import date

import pytest
from sqlalchemy import select

from smdx_api.db.models import DisplayStockEntry, Proposal
from tests.conftest import jst

URL = "/api/production/display-stock"


def body(department="DELI", target="2026-10-16", items=None):
    return {"department_code": department, "target_date": target,
            "items": [{"product_code": "DELI-001", "quantity": 3}] if items is None else items}


def deli_rows(client):
    res = client.get("/api/proposals", params={"department_code": "DELI", "target_date": "2026-10-16"})
    assert res.status_code == 200, res.text
    return {r["time_band"]: r for r in res.json()["proposals"]}


@pytest.mark.db
def test_display_stock_saves_and_recalculates_approved_as_diff(client, login, user_factory, deli_setup, test_services,
                                                               fixed_now):
    login(client, user_factory(departments=("DELI",)))
    deli_rows(client)  # 作成
    b14 = deli_rows(client)[14]
    res = client.post(f"/api/proposals/{b14['id']}/approve", json={"expected_qty": b14["proposed_qty"]})
    assert res.status_code == 200, res.text
    fixed_now.set(jst(2026, 10, 16, 12, 0))
    res = client.put(URL, json=body())
    assert res.status_code == 200, res.text
    assert res.json()["saved"] == 1 and res.json()["job"]["status"] == "running" and res.json()["job"]["total"] == 2
    after = deli_rows(client)
    # 承認済みの時間帯は数量を変えず、再計算値(ceil(3.3 − 3) = 1)を差分として持つ
    assert after[14]["status"] == "approved" and after[14]["proposed_qty"] == b14["proposed_qty"]
    assert after[14]["recalculated_qty"] == 1
    # 未承認の17時帯は直後の時間帯ではないので変わらない(陳列残数0)
    assert after[17]["proposed_qty"] == 10 and after[17]["display_stock_qty"] == 0


@pytest.mark.db
def test_display_stock_updates_pending_band(client, login, user_factory, deli_setup, test_services, fixed_now, db):
    login(client, user_factory(departments=("DELI",)))
    deli_rows(client)
    fixed_now.set(jst(2026, 10, 16, 12, 0))
    assert client.put(URL, json=body()).status_code == 200
    row = deli_rows(client)[14]
    assert (row["proposed_qty"], row["display_stock_qty"], row["status"]) == (1, 3, "pending")
    # 同じ入力時刻で入れ直すと上書きする
    assert client.put(URL, json=body(items=[{"product_code": "DELI-001", "quantity": 0}])).json()["saved"] == 1
    entries = list(db.scalars(select(DisplayStockEntry)))
    assert [(e.quantity, e.entered_by is not None) for e in entries] == [(0, True)]
    assert deli_rows(client)[14]["proposed_qty"] == 4


@pytest.mark.db
@pytest.mark.parametrize("sent", ["2026-10-16T10:58:00+09:00", "2026-10-16T12:02:00+09:00"])
def test_display_stock_entered_at_is_server_now(client, login, user_factory, deli_setup, test_services, fixed_now, db,
                                                sent):
    """入力時刻は保存時のサーバーの時刻。端末の時計が遅れて(進んで)いても、送られた時刻は使わない。"""
    login(client, user_factory(departments=("DELI",)))
    deli_rows(client)
    fixed_now.set(jst(2026, 10, 16, 12, 0))
    res = client.put(URL, json={**body(), "entered_at": sent})
    assert res.status_code == 200, res.text
    assert res.json()["entered_at"] == "2026-10-16T12:00:00+09:00"
    assert [e.entered_at for e in db.scalars(select(DisplayStockEntry))] == [jst(2026, 10, 16, 12, 0)]
    # 遅れた時刻(10:58)を使うと 11時帯(製造開始済み)に入り効かないが、12:00 なので 14時帯に効く
    assert deli_rows(client)[14]["proposed_qty"] == 1


@pytest.mark.db
def test_display_stock_for_fresh_department_is_400(client, login, user_factory, veg_setup, test_services, db):
    login(client, user_factory(departments=("VEG",)))
    res = client.put(URL, json=body(department="VEG", items=[]))
    assert res.status_code == 400 and res.json()["detail"] == "部門と業務の組合せが正しくありません"
    assert list(db.scalars(select(Proposal))) == []


@pytest.mark.db
def test_display_stock_other_department_403(client, login, user_factory, deli_setup):
    login(client, user_factory(departments=("VEG",)))
    assert client.put(URL, json=body()).status_code == 403


@pytest.mark.db
def test_display_stock_requires_csrf_header(app, user_factory, deli_setup):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    u = user_factory(departments=("DELI",))
    c.post("/api/auth/login", json={"login_id": u.login_id, "password": "pass1234"}, headers={"X-Requested-With": "smdx"})
    assert c.put(URL, json=body()).status_code == 403


@pytest.mark.db
def test_display_stock_target_other_than_today_is_400(client, login, user_factory, deli_setup, db):
    """陳列残数は当日の分だけ。翌日以降の分を受け付けると、入力した時刻だけで翌日の時間帯から差し引いてしまう。"""
    login(client, user_factory(departments=("DELI",)))
    for d in ("2026-10-15", "2026-10-17", "2026-11-01"):
        res = client.put(URL, json=body(target=d))
        assert res.status_code == 400 and res.json()["detail"] == "陳列残数は当日の分だけ入力できます"
    assert list(db.scalars(select(DisplayStockEntry))) == []


# 422 では保存を取り消す(試験ではログインも巻き戻るため、1回の要求ずつ確かめる)
@pytest.mark.db
@pytest.mark.parametrize("override,detail", [
    ({"items": [{"product_code": "VEG-009", "quantity": 1}]}, "この部門の商品ではありません: VEG-009"),
    ({"items": [{"product_code": "NOPE", "quantity": 1}]}, "未登録の商品コードです: NOPE"),
    ({"items": [{"product_code": "DELI-001", "quantity": -1}]}, None),
])
def test_display_stock_validation(client, login, user_factory, deli_setup, product_factory, db, override, detail):
    product_factory(code="VEG-009")
    login(client, user_factory(departments=("DELI",)))
    res = client.put(URL, json={**body(), **override})
    assert res.status_code == 422
    if detail is not None:
        assert res.json()["detail"] == detail
    assert list(db.scalars(select(DisplayStockEntry))) == []


@pytest.mark.db
def test_save_display_stock_dedups_same_product(db, deli_setup):
    from smdx_api.imports.manual import save_display_stock
    from tests.conftest import dept

    n = save_display_stock(db, dept(db, "DELI"), date(2026, 10, 16), jst(2026, 10, 16, 12),
                           [("DELI-001", 3), ("DELI-001", 5)], None)
    assert n == 1 and [e.quantity for e in db.scalars(select(DisplayStockEntry))] == [5]
