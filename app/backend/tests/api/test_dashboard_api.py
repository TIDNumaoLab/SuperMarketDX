"""今日の状況の API(詳細設計書「今日の状況(GET /api/dashboard)の項目」「きっかけ」)。"""
from datetime import date

import pytest
from sqlalchemy import func, select

from smdx_api.db.models import CalendarDay, ImportLog, ProposalJob, Promotion
from smdx_api.weather_client.store import save_forecast
from tests.conftest import dept, jst
from tests.fakes import hourly_rows


def get_dashboard(client):
    res = client.get("/api/dashboard")
    assert res.status_code == 200, res.text
    return res.json()


def job_count(db) -> int:
    return db.scalar(select(func.count()).select_from(ProposalJob))


@pytest.mark.db
def test_requires_login(app):
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/api/dashboard").status_code == 401


@pytest.mark.db
def test_staff_sees_own_departments_and_manager_sees_all(client, login, user_factory, fixed_now, test_services):
    login(client, user_factory(departments=("FISH",)))
    body = get_dashboard(client)
    assert body["now"] == "2026-10-16T10:00:00+09:00"
    assert [d["department_code"] for d in body["departments"]] == ["FISH"]
    assert [d["department_code"] for d in body["data_status"]] == ["FISH"]
    client.post("/api/auth/logout")
    login(client, user_factory(role="manager", departments=()))
    body = get_dashboard(client)
    assert [(d["department_code"], d["department_name"], d["business_type"]) for d in body["departments"]] == [
        ("DELI", "惣菜", "production"), ("FISH", "鮮魚", "order"), ("VEG", "青果", "order")]


@pytest.mark.db
def test_starts_recalc_only_where_needed(client, login, user_factory, veg_setup, test_services, db):
    login(client, user_factory(departments=("VEG", "FISH")))
    first = get_dashboard(client)
    veg = next(d for d in first["departments"] if d["department_code"] == "VEG")
    fish = next(d for d in first["departments"] if d["department_code"] == "FISH")
    # VEG は提案が未作成なのでジョブを始める。FISH は商品が無いので始めない
    assert veg["job"]["status"] == "running" and veg["last_job"] is None
    assert fish["job"] is None and fish["last_job"] is None
    # 今日の状況はジョブを待たず、保存済みの提案から数える(この時点では0件)
    assert first["deadlines"] == []
    # TestClient は応答の後にジョブを実行する → 次に開くと最新なので始めず、最後のジョブが成功で返る
    second = get_dashboard(client)
    veg = next(d for d in second["departments"] if d["department_code"] == "VEG")
    assert veg["job"] is None and veg["last_job"]["status"] == "succeeded" and veg["last_job"]["error"] is None
    assert job_count(db) == 1
    assert second["deadlines"][0]["pending"] == 1


@pytest.mark.db
def test_jobs_of_several_departments_all_finish(client, login, user_factory, veg_setup, product_factory, test_services,
                                                db):
    """複数部門で開始したジョブ(並行して実行する)が、いずれも最後まで実行される。"""
    product_factory(code="FISH-P1", department="FISH")
    login(client, user_factory(role="manager", departments=()))
    first = {d["department_code"]: d for d in get_dashboard(client)["departments"]}
    assert first["VEG"]["job"]["status"] == "running" and first["FISH"]["job"]["status"] == "running"
    second = {d["department_code"]: d for d in get_dashboard(client)["departments"]}
    assert [second[c]["last_job"]["status"] for c in ("VEG", "FISH")] == ["succeeded", "succeeded"]
    assert second["VEG"]["job"] is None and second["FISH"]["job"] is None


@pytest.mark.db
def test_last_job_is_of_default_view_and_business_hours(client, login, user_factory, test_services, db, fixed_now):
    """最後のジョブは既定表示のものだけ(別の対象日を指定した再計算の失敗は出さない)。営業時間を返す。"""
    from smdx_api.proposals.jobs import JobKey, start_or_get_job

    other, _ = start_or_get_job(db, dept(db, "VEG"), JobKey("date", date(2026, 10, 20)), fixed_now.value, total=1)
    other.status, other.error, other.finished_at = "failed", "失敗", fixed_now.value
    db.commit()
    login(client, user_factory(departments=("VEG",)))
    body = get_dashboard(client)
    assert body["departments"][0]["last_job"] is None
    assert body["business_hours"] == {"open": "10:00", "close": "20:00"}


@pytest.mark.db
def test_running_job_is_returned_not_duplicated(client, login, user_factory, veg_setup, test_services, db, fixed_now):
    from smdx_api.proposals.jobs import JobKey, start_or_get_job

    running, _ = start_or_get_job(db, dept(db, "VEG"), JobKey("default", date(2026, 10, 16)), fixed_now.value, total=1)
    login(client, user_factory(departments=("VEG",)))
    body = get_dashboard(client)
    assert body["departments"][0]["job"]["id"] == running.id
    assert job_count(db) == 1


@pytest.mark.db
def test_fresh_list_with_target_date_shares_running_default_job(client, login, user_factory, veg_setup, test_services,
                                                                db, fixed_now):
    """今日の状況が始めた既定表示のジョブを、対象日を選んで開いた発注画面でも返す(二重に計算しない)。"""
    from smdx_api.proposals.jobs import JobKey, start_or_get_job

    # 10/16 15:00(締め 20:00 より前)。VEG-001 は LT1 なので既定表示の納品日は 10/17
    running, _ = start_or_get_job(db, dept(db, "VEG"), JobKey("default", date(2026, 10, 16)), fixed_now.value, total=1)
    login(client, user_factory(departments=("VEG",)))
    res = client.get("/api/proposals", params={"department_code": "VEG", "target_date": "2026-10-17"})
    assert res.status_code == 200, res.text
    assert res.json()["job"]["id"] == running.id
    assert job_count(db) == 1
    # 既定表示のジョブが計算しない納品日(10/18)を指定したときは、その日のジョブを始める
    res = client.get("/api/proposals", params={"department_code": "VEG", "target_date": "2026-10-18"})
    assert res.json()["job"]["id"] != running.id
    assert job_count(db) == 2


@pytest.mark.db
def test_deadlines_grouped_and_counted(client, login, user_factory, fixed_now, test_services, db, product_factory,
                                       proposal_factory):
    fixed_now.set(jst(2026, 10, 16, 14, 20))
    veg1, veg2, veg3 = (product_factory(code=f"VEG-D{i}") for i in range(3))
    fish = product_factory(code="FISH-D1", department="FISH")
    deli = product_factory(code="DELI-D1", department="DELI")
    cutoff = jst(2026, 10, 16, 15)
    proposal_factory(veg1, deadline=cutoff)
    proposal_factory(veg2, deadline=cutoff, warnings=["NO_INVENTORY"])
    proposal_factory(veg3, deadline=cutoff, status="approved")
    # 期限を過ぎた未承認は期限切れにしてから数える
    proposal_factory(veg1, target=date(2026, 10, 16), deadline=jst(2026, 10, 16, 9))
    # 翌日の期限でも24時間以内なら入る。24時間より先・前日の期限は入らない
    proposal_factory(fish, target=date(2026, 10, 18), deadline=jst(2026, 10, 17, 9))
    proposal_factory(fish, target=date(2026, 10, 19), deadline=jst(2026, 10, 17, 15))
    proposal_factory(fish, target=date(2026, 10, 15), deadline=jst(2026, 10, 15, 20), status="confirmed")
    # 惣菜は現在の区切りにある時間帯だけ。区切りに無い時間帯(12時)の提案は数えない
    proposal_factory(deli, target=date(2026, 10, 16), time_band=17, deadline=jst(2026, 10, 16, 16))
    proposal_factory(deli, target=date(2026, 10, 16), time_band=12, deadline=jst(2026, 10, 16, 11))
    login(client, user_factory(role="manager", departments=()))
    body = get_dashboard(client)
    got = [(d["department_code"], d["deadline"], d["target_date"], d["time_band"], d["pending"], d["approved"],
            d["confirmed"], d["expired"], d["bulk_approvable"], d["warnings"]) for d in body["deadlines"]]
    assert got == [
        ("VEG", "2026-10-16T09:00:00+09:00", "2026-10-16", None, 0, 0, 0, 1, 0, []),
        ("VEG", "2026-10-16T15:00:00+09:00", "2026-10-17", None, 2, 1, 0, 0, 1, [{"code": "NO_INVENTORY", "count": 1}]),
        ("DELI", "2026-10-16T16:00:00+09:00", "2026-10-16", 17, 1, 0, 0, 0, 1, []),
        ("FISH", "2026-10-17T09:00:00+09:00", "2026-10-18", None, 1, 0, 0, 0, 1, []),
    ]


@pytest.mark.db
def test_staff_deadlines_only_own_department(client, login, user_factory, fixed_now, test_services, product_factory,
                                             proposal_factory):
    proposal_factory(product_factory(code="FISH-S1", department="FISH"), deadline=jst(2026, 10, 16, 15))
    proposal_factory(product_factory(code="VEG-S1"), deadline=jst(2026, 10, 16, 15))
    login(client, user_factory(departments=("VEG",)))
    assert [d["department_code"] for d in get_dashboard(client)["deadlines"]] == ["VEG"]


@pytest.mark.db
def test_tomorrow_conditions(client, login, user_factory, fixed_now, test_services, db, product_factory):
    tomorrow = date(2026, 10, 17)
    # 古い取得と新しい取得があれば新しい方。営業時間(10〜20時)の中で集約する
    save_forecast(db, jst(2026, 10, 16, 6), hourly_rows(tomorrow, tomorrow, code=1, temperature=10.0))
    from dataclasses import replace

    changes = {12: dict(weather_code=61, precipitation=4.5), 14: dict(temperature=18.0),
               3: dict(temperature=5.0)}  # 3時は営業時間外なので数えない
    rows = [replace(r, **changes.get(r.time.hour, {}))
            for r in hourly_rows(tomorrow, tomorrow, code=3, temperature=15.0, precipitation=0.0)]
    save_forecast(db, jst(2026, 10, 16, 9, 30), rows)
    veg = product_factory(code="VEG-T1", name="りんご")
    fish = product_factory(code="FISH-T1", department="FISH", name="さんま")
    db.add_all([
        Promotion(product_id=veg.id, start_date=date(2026, 10, 16), end_date=date(2026, 10, 18), description="2割引"),
        Promotion(product_id=fish.id, start_date=tomorrow, end_date=tomorrow, description="1尾100円"),
        Promotion(product_id=veg.id, start_date=date(2026, 10, 18), end_date=date(2026, 10, 19), description="翌々日"),
        CalendarDay(date=tomorrow, kind="event", name="ハロウィン"),
        CalendarDay(date=date(2026, 10, 18), kind="event", name="翌々日の行事"),
    ])
    db.flush()
    login(client, user_factory(departments=("VEG",)))
    t = get_dashboard(client)["tomorrow"]
    assert t["date"] == "2026-10-17"
    assert t["weather"] == {"weather_code": 61, "weather_label": "雨", "temperature": 18.0, "temperature_min": 15.0,
                            "precipitation": 4.5, "fetched_at": "2026-10-16T09:30:00+09:00"}
    # 担当者は閲覧できる部門の特売だけ
    assert t["promotions"] == [{"department_name": "青果", "product_name": "りんご", "start_date": "2026-10-16",
                                "end_date": "2026-10-18", "description": "2割引"}]
    assert t["calendar"] == [{"kind": "event", "name": "ハロウィン"}]


@pytest.mark.db
def test_tomorrow_weather_null_without_forecast_and_no_weather_api(client, login, user_factory, fixed_now,
                                                                    test_services):
    login(client, user_factory(departments=("FISH",)))
    t = get_dashboard(client)["tomorrow"]
    assert t["weather"] is None and t["promotions"] == [] and t["calendar"] == []
    assert test_services.weather_client.calls == 0


@pytest.mark.db
def test_data_status(client, login, user_factory, fixed_now, test_services, db, product_factory, add_pos,
                     add_inventory):
    veg = product_factory(code="VEG-X1")
    deli = product_factory(code="DELI-X1", department="DELI")
    add_pos(veg, date(2026, 10, 15), 5)
    add_pos(deli, date(2026, 10, 13), 5, 12)
    add_inventory(veg, jst(2026, 10, 15, 19), 3)
    add_inventory(veg, jst(2026, 10, 16, 8, 15), 4)
    add_inventory(veg, jst(2026, 10, 16, 11), 9)  # 現在(10:00)より後の基準日時は使わない
    db.add(ImportLog(kind="pos", department_id=dept(db, "VEG").id, file_name="a.csv", imported_count=1,
                     skipped_count=0, finished_at=jst(2026, 10, 16, 7, 40)))
    db.add(ImportLog(kind="waste", department_id=dept(db, "VEG").id, file_name="w.csv", imported_count=1,
                     skipped_count=0, finished_at=jst(2026, 10, 16, 8)))
    db.flush()
    login(client, user_factory(role="manager", departments=()))
    status = {s["department_code"]: s for s in get_dashboard(client)["data_status"]}
    assert status["VEG"] == {"department_code": "VEG", "pos_latest_date": "2026-10-15",
                             "pos_imported_at": "2026-10-16T07:40:00+09:00",
                             "inventory_based_at": "2026-10-16T08:15:00+09:00", "stale_pos": False}
    # 惣菜は在庫を持たない。既定の対象日(10:00 は最初の製造開始より後なので翌日)の基準日は当日の前日
    assert status["DELI"] == {"department_code": "DELI", "pos_latest_date": "2026-10-13", "pos_imported_at": None,
                              "inventory_based_at": None, "stale_pos": True}
    assert status["FISH"]["pos_latest_date"] is None and status["FISH"]["stale_pos"] is True


@pytest.mark.db
def test_failed_last_job_is_returned(client, login, user_factory, fixed_now, test_services, db):
    db.add(ProposalJob(department_id=dept(db, "FISH").id, scope="default", target_date=date(2026, 10, 16),
                       status="failed", error="計算中にエラーが発生しました。時間をおいて再計算してください",
                       started_at=jst(2026, 10, 16, 9), finished_at=jst(2026, 10, 16, 9, 1)))
    db.flush()
    login(client, user_factory(departments=("FISH",)))
    last = get_dashboard(client)["departments"][0]["last_job"]
    assert last == {"status": "failed", "finished_at": "2026-10-16T09:01:00+09:00",
                    "error": "計算中にエラーが発生しました。時間をおいて再計算してください"}
