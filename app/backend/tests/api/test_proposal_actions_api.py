"""提案の操作の API(詳細設計書「API仕様」「提案の状態遷移」「エラー応答」)。"""
import pytest


@pytest.mark.db
@pytest.mark.parametrize("call,status", [
    (lambda c, i: c.patch(f"/api/proposals/{i}", json={"quantity": -1, "reason": "other"}), 422),
    (lambda c, i: c.patch(f"/api/proposals/{i}", json={"quantity": 3}), 422),           # 修正理由なし
    (lambda c, i: c.patch(f"/api/proposals/{i}", json={"quantity": 3, "reason": "bad"}), 422),
    (lambda c, i: c.patch(f"/api/proposals/{i}", json={"quantity": 1.5, "reason": "other"}), 422),
    (lambda c, i: c.patch(f"/api/proposals/{i}", json={"quantity": 3, "reason": "other", "reason_note": "あ" * 129}), 422),
    (lambda c, i: c.post(f"/api/proposals/{i}/cancel-approval"), 409),                  # 未承認の取消
    (lambda c, i: c.post(f"/api/proposals/{i}/adopt-recalculated"), 409),
    (lambda c, i: c.patch("/api/proposals/999999", json={"quantity": 3, "reason": "other"}), 404),
    (lambda c, i: c.post("/api/proposals/999999/approve", json={"expected_qty": 10}), 404),
    (lambda c, i: c.post(f"/api/proposals/{i}/approve", json={}), 422),                 # 表示していた数量なし,
])
def test_action_errors(client, login, user_factory, proposal_factory, fixed_now, call, status):
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory()
    assert call(client, p.id).status_code == status


@pytest.mark.db
def test_adjust_and_conflict_messages(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(qty=24)
    res = client.patch(f"/api/proposals/{p.id}", json={"quantity": 18, "reason": "weather", "reason_note": "雨予報"})
    assert res.status_code == 200
    body = res.json()
    assert (body["proposed_qty"], body["original_qty"], body["is_adjusted"], body["adjust_reason"], body["adjust_note"]) == (
        18, 24, True, "weather", "雨予報")
    client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 18})
    res = client.patch(f"/api/proposals/{p.id}", json={"quantity": 3, "reason": "other"})
    assert res.status_code == 409 and res.json()["detail"] == "承認済みの提案は修正できません"


@pytest.mark.db
def test_approve_with_warning_requires_confirm(client, login, user_factory, proposal_factory, fixed_now):
    u = user_factory(name="青果 一郎", departments=("VEG",))
    login(client, u)
    p = proposal_factory(warnings=["NO_INVENTORY"])
    res = client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10})
    assert res.status_code == 422 and res.json()["detail"] == "警告を確認してください"
    body = client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10, "confirm_warnings": True}).json()
    assert (body["status"], body["approved_by_name"], body["approved_at"]) == (
        "approved", "青果 一郎", "2026-10-16T10:00:00+09:00")


@pytest.mark.db
def test_approve_with_changed_quantity_is_409(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(qty=24)
    res = client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 20})
    assert res.status_code == 409 and res.json()["detail"] == "数量が更新されました。一覧を取り直してから承認してください"
    body = client.post("/api/proposals/approve-bulk", json={"items": [{"id": p.id, "expected_qty": 20}]}).json()
    assert body == {"approved_ids": [], "skipped": [{"id": p.id, "reason": "数量が更新されたため一括承認から除外しました"}]}


@pytest.mark.db
def test_cancel_after_deadline_is_409(client, login, user_factory, proposal_factory, fixed_now):
    from tests.conftest import jst

    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(status="approved", deadline=jst(2026, 10, 16, 20))
    fixed_now.set(jst(2026, 10, 16, 20))
    res = client.post(f"/api/proposals/{p.id}/cancel-approval")
    assert res.status_code == 409


@pytest.mark.db
def test_failed_action_keeps_deadline_update_and_runs_it_once(client, login, user_factory, proposal_factory, fixed_now,
                                                              db, monkeypatch):
    """期限経過の更新は操作が条件違反でも残す。更新は1回の要求で1度だけ、提案の部門に限って行う。"""
    from smdx_api.proposals import actions, deadlines
    from tests.conftest import jst

    calls = []

    def counting(db_, now, department_id=None):
        calls.append(department_id)
        return deadlines.apply_deadlines(db_, now, department_id)

    monkeypatch.setattr(actions, "apply_deadlines", counting)
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(deadline=jst(2026, 10, 16, 20))
    fixed_now.set(jst(2026, 10, 16, 20))
    res = client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10})
    assert res.status_code == 409 and res.json()["detail"] == "未承認の提案ではありません"
    db.refresh(p)
    assert p.status == "expired"
    assert calls == [p.department_id]


@pytest.mark.db
def test_cancel_and_adopt_api(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(status="approved", qty=24, recalculated_qty=30)
    body = client.post(f"/api/proposals/{p.id}/cancel-approval").json()
    assert (body["status"], body["is_adjusted"], body["approved_by"]) == ("pending", True, None)
    body = client.post(f"/api/proposals/{p.id}/adopt-recalculated").json()
    assert (body["proposed_qty"], body["recalculated_qty"], body["is_adjusted"]) == (30, None, False)


@pytest.mark.db
def test_bulk_approve_api(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(departments=("VEG",)))
    ok = proposal_factory()
    warn = proposal_factory(warnings=["NO_WEATHER"], product_offset=1)
    res = client.post("/api/proposals/approve-bulk", json={"items": [{"id": ok.id, "expected_qty": 10}, {"id": warn.id, "expected_qty": 10},
                                                                   {"id": 999999, "expected_qty": 0}]})
    assert res.status_code == 200
    assert res.json() == {"approved_ids": [ok.id], "skipped": [
        {"id": warn.id, "reason": "警告があるため一括承認から除外しました"}, {"id": 999999, "reason": "対象が見つかりません"}]}
    assert client.post("/api/proposals/approve-bulk", json={"items": []}).status_code == 422


@pytest.mark.db
def test_bulk_approve_item_limit(client, login, user_factory, proposal_factory, fixed_now):
    # 1〜1000件。1001件は 422
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory()
    items = [{"id": 999999 - i, "expected_qty": 0} for i in range(999)] + [{"id": p.id, "expected_qty": 10}]
    res = client.post("/api/proposals/approve-bulk", json={"items": items})
    assert res.status_code == 200 and res.json()["approved_ids"] == [p.id]
    over = items + [{"id": 1, "expected_qty": 0}]
    assert client.post("/api/proposals/approve-bulk", json={"items": over}).status_code == 422


@pytest.mark.db
def test_bulk_approve_duplicate_id_uses_first(client, login, user_factory, proposal_factory, fixed_now, db):
    # 同じ ID が重なれば最初のものを使う(後の数量では承認しない)
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(qty=10)
    res = client.post("/api/proposals/approve-bulk", json={"items": [{"id": p.id, "expected_qty": 9},
                                                                   {"id": p.id, "expected_qty": 10}]})
    assert res.status_code == 200
    assert res.json() == {"approved_ids": [], "skipped": [{"id": p.id, "reason": "数量が更新されたため一括承認から除外しました"}]}
    db.refresh(p)
    assert p.status == "pending"
    res = client.post("/api/proposals/approve-bulk", json={"items": [{"id": p.id, "expected_qty": 10},
                                                                   {"id": p.id, "expected_qty": 9}]})
    assert res.json() == {"approved_ids": [p.id], "skipped": []}


@pytest.mark.db
def test_staff_cannot_touch_other_department(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(departments=("FISH",)))
    p = proposal_factory()  # VEG の提案
    assert client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10}).status_code == 403
    assert client.patch(f"/api/proposals/{p.id}", json={"quantity": 3, "reason": "other"}).status_code == 403
    assert client.post(f"/api/proposals/{p.id}/cancel-approval").status_code == 403
    assert client.post(f"/api/proposals/{p.id}/adopt-recalculated").status_code == 403
    res = client.post("/api/proposals/approve-bulk", json={"items": [{"id": p.id, "expected_qty": 10}]})
    assert res.status_code == 403
    assert client.get("/api/proposals", params={"department_code": "VEG"}).status_code == 403


@pytest.mark.db
def test_bulk_with_mixed_departments_approves_nothing(client, login, user_factory, proposal_factory, product_factory,
                                                     fixed_now, db):
    login(client, user_factory(departments=("FISH",)))
    own = proposal_factory(product_factory(code="FISH-001", department="FISH"))
    other = proposal_factory()  # VEG
    assert client.post("/api/proposals/approve-bulk", json={"items": [{"id": own.id, "expected_qty": 10},
                                                                  {"id": other.id, "expected_qty": 10}]}).status_code == 403
    db.refresh(own)
    assert own.status == "pending"


@pytest.mark.db
def test_manager_can_operate_any_department(client, login, user_factory, proposal_factory, fixed_now):
    login(client, user_factory(role="manager", departments=()))
    p = proposal_factory()
    assert client.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10}).status_code == 200


@pytest.mark.db
def test_actions_require_csrf_header(app, user_factory, proposal_factory, fixed_now):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    u = user_factory(departments=("VEG",))
    c.post("/api/auth/login", json={"login_id": u.login_id, "password": "pass1234"}, headers={"X-Requested-With": "smdx"})
    p = proposal_factory()
    assert c.post(f"/api/proposals/{p.id}/approve", json={"expected_qty": 10}).status_code == 403


@pytest.mark.db
def test_adjust_fresh_requires_multiple_of_order_unit(client, login, user_factory, product_factory, proposal_factory,
                                                      fixed_now):
    """生鮮の数量修正は発注単位(入数)の倍数に限る。倍数でなければ保存せず 422。"""
    login(client, user_factory(departments=("VEG",)))
    p = proposal_factory(product_factory(order_unit=6), qty=12)
    res = client.patch(f"/api/proposals/{p.id}", json={"quantity": 7, "reason": "other"})
    assert res.status_code == 422 and res.json()["detail"] == "発注単位(6)の倍数で入力してください"
    for qty in (0, 18):
        res = client.patch(f"/api/proposals/{p.id}", json={"quantity": qty, "reason": "other"})
        assert res.status_code == 200 and res.json()["proposed_qty"] == qty


@pytest.mark.db
def test_adjust_deli_is_not_limited_by_order_unit(client, login, user_factory, product_factory, proposal_factory,
                                                  fixed_now):
    """惣菜の製造数は発注単位で丸めないため、倍数でなくても保存できる。"""
    login(client, user_factory(departments=("DELI",)))
    p = proposal_factory(product_factory(department="DELI", order_unit=6), time_band=14, qty=12)
    res = client.patch(f"/api/proposals/{p.id}", json={"quantity": 7, "reason": "other"})
    assert res.status_code == 200 and res.json()["proposed_qty"] == 7
