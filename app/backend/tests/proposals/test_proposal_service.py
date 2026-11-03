"""自動再計算の判定とジョブの対象日(詳細設計書「自動再計算の対象と判定」「二重実行防止」)。"""
from datetime import date, timedelta

import pytest

from smdx_api.db.models import ImportLog, InventorySnapshot
from smdx_api.proposals.compute_fresh import ComputeServices, FreshTargets, compute_fresh
from smdx_api.proposals.persist import apply_computed
from smdx_api.proposals.jobs import JobKey
from smdx_api.proposals.service import job_key, needs_auto_recalc
from smdx_api.settings.service import EVENTS_CHANGED_KEY, load_settings, touch_internal
from tests.conftest import dept, jst
from tests.fake_models import const_registry


def create_all(db, services, now, targets=FreshTargets(None)):
    veg = dept(db, "VEG")
    items, _ = compute_fresh(db, veg, now, load_settings(db), services, targets)
    apply_computed(db, veg, items, now)


def needs(db, services, now, targets=FreshTargets(None)):
    return needs_auto_recalc(db, dept(db, "VEG"), now, load_settings(db), services, targets)


@pytest.mark.db
def test_job_key(db, fixed_now):
    s, veg = load_settings(db), dept(db, "VEG")
    assert job_key(veg, jst(2026, 10, 16, 19, 59), s, FreshTargets(None)) == JobKey("default", date(2026, 10, 16))
    # 締め時刻以後の最も早い納品日に向けた発注日は翌日
    assert job_key(veg, jst(2026, 10, 16, 20), s, FreshTargets(None)) == JobKey("default", date(2026, 10, 17))
    # 対象日の指定は納品日。既定表示の発注日と同じ日付でも別の種別
    assert job_key(veg, jst(2026, 10, 16, 10), s, FreshTargets(date(2026, 10, 17))) == JobKey("date", date(2026, 10, 17))


@pytest.mark.db
def test_needs_auto_recalc_when_missing_then_fresh(db, veg_setup, baseline_services, fixed_now, product_factory):
    now = fixed_now.value
    assert needs(db, baseline_services, now)                     # 未作成
    create_all(db, baseline_services, now)
    assert not needs(db, baseline_services, now + timedelta(hours=1))
    product_factory(code="VEG-002")                              # 新しい商品の提案が未作成
    assert needs(db, baseline_services, now + timedelta(hours=1))


@pytest.mark.db
def test_needs_auto_recalc_on_data_change(db, veg_setup, baseline_services, fixed_now):
    now = fixed_now.value
    create_all(db, baseline_services, now)
    db.add(InventorySnapshot(based_at=jst(2026, 10, 16, 15, 30), product_id=veg_setup.id, quantity=3, source="manual",
                             updated_at=now + timedelta(minutes=30)))
    db.flush()
    assert needs(db, baseline_services, now + timedelta(hours=1))


@pytest.mark.db
def test_needs_auto_recalc_on_pos_import_and_events(db, veg_setup, baseline_services, fixed_now):
    now = fixed_now.value
    create_all(db, baseline_services, now)
    touch_internal(db, EVENTS_CHANGED_KEY, now + timedelta(minutes=5))
    assert needs(db, baseline_services, now + timedelta(hours=1))
    create_all(db, baseline_services, now + timedelta(hours=1))
    db.add(ImportLog(kind="pos", department_id=dept(db, "VEG").id, file_name="p.csv", imported_count=1,
                     skipped_count=0, errors=[], finished_at=now + timedelta(hours=1, minutes=1)))
    db.flush()
    assert needs(db, baseline_services, now + timedelta(hours=2))


@pytest.mark.db
def test_needs_auto_recalc_on_weather_age_and_model_change(db, veg_setup, baseline_services, fixed_now, tmp_path):
    now = fixed_now.value
    create_all(db, baseline_services, now)
    assert needs(db, baseline_services, now + timedelta(hours=3))   # 予報の取得から3時間
    model = ComputeServices(const_registry(tmp_path), baseline_services.weather_client)
    assert needs(db, model, now + timedelta(hours=1))               # モデルの版が変わった


@pytest.mark.db
def test_needs_auto_recalc_after_adopt(db, veg_setup, baseline_services, fixed_now):
    from sqlalchemy import select

    from smdx_api.db.models import Proposal

    now = fixed_now.value
    create_all(db, baseline_services, now)
    p = db.scalars(select(Proposal)).one()
    p.basis = {**p.basis, "recalc_pending": True}
    db.flush()
    assert needs(db, baseline_services, now + timedelta(minutes=1))


@pytest.mark.db
def test_adjusted_or_approved_do_not_trigger(db, veg_setup, baseline_services, fixed_now):
    from sqlalchemy import select

    from smdx_api.db.models import Proposal

    now = fixed_now.value
    create_all(db, baseline_services, now)
    p = db.scalars(select(Proposal)).one()
    p.is_adjusted = True
    db.flush()
    # 修正ありだけが古い → 自動では再計算しない
    assert not needs(db, baseline_services, now + timedelta(hours=4))
    p.is_adjusted, p.status = False, "approved"
    db.flush()
    assert not needs(db, baseline_services, now + timedelta(hours=4))


@pytest.mark.db
def test_needs_auto_recalc_explicit_date(db, veg_setup, baseline_services, fixed_now):
    now = fixed_now.value
    create_all(db, baseline_services, now)
    # 既定表示の提案(10/17)はあるが、10/20 の提案は未作成
    assert needs(db, baseline_services, now, FreshTargets(date(2026, 10, 20)))
    create_all(db, baseline_services, now, FreshTargets(date(2026, 10, 20)))
    assert not needs(db, baseline_services, now, FreshTargets(date(2026, 10, 20)))


@pytest.mark.db
def test_no_weather_proposal_does_not_retrigger_immediately(db, veg_setup, fixed_now, tmp_path):
    """予報が取れずに作った提案を、作った直後に「古い」と判定し続けない(再計算が止まらなくなるため)。"""
    from tests.fakes import FailingWeatherClient

    now = fixed_now.value
    services = ComputeServices(const_registry(tmp_path), FailingWeatherClient())
    create_all(db, services, now)
    assert not needs(db, services, now + timedelta(minutes=1))
    # 判定時間が過ぎたら取り直す
    assert needs(db, services, now + timedelta(hours=3))


@pytest.mark.db
def test_row_baseline_with_loaded_model_is_not_model_change(db, veg_setup, fixed_now, tmp_path):
    """モデルを読み込んでいても行がベースラインで予測された提案は、モデルの版の変更とみなさない。"""
    from smdx_api.db.models import Proposal
    from sqlalchemy import select

    now = fixed_now.value
    services = ComputeServices(const_registry(tmp_path), baseline_services_weather())
    create_all(db, services, now)
    p = db.scalars(select(Proposal)).one()
    p.basis = {**p.basis, "model_version": "baseline"}  # 対象日の行だけ気象が欠けてベースラインになった場合
    db.flush()
    assert not needs(db, services, now + timedelta(minutes=1))


def baseline_services_weather():
    from tests.fakes import FakeWeatherClient
    return FakeWeatherClient()


@pytest.mark.db
def test_adopt_then_recalc_clears_recalc_pending(db, veg_setup, baseline_services, fixed_now, user_factory):
    # 採用 → 次の判定で再計算 → 印が消えて、再計算を繰り返さない(PR #7 レビューの指摘8)
    from sqlalchemy import select

    from smdx_api.db.models import Proposal
    from smdx_api.proposals.actions import RECALC_PENDING, adopt_recalculated

    now = fixed_now.value
    create_all(db, baseline_services, now)
    p = db.scalars(select(Proposal)).one()
    p.is_adjusted, p.proposed_qty, p.recalculated_qty = True, 12, p.proposed_qty
    db.flush()
    adopt_recalculated(db, p.id, user_factory().id, now + timedelta(minutes=1))
    assert p.basis[RECALC_PENDING] is True
    assert needs(db, baseline_services, now + timedelta(minutes=2))
    create_all(db, baseline_services, now + timedelta(minutes=2))
    db.refresh(p)
    assert RECALC_PENDING not in p.basis
    assert not needs(db, baseline_services, now + timedelta(minutes=3))


def test_launch_parallel_runs_jobs_concurrently(monkeypatch):
    """今日の状況で開始した複数部門のジョブは、1つずつではなく並行して実行する。"""
    import threading

    from fastapi import BackgroundTasks

    from smdx_api.proposals import service

    # 3つのジョブがそろって待ち合わせられなければ(順に実行すると)タイムアウトで失敗する
    barrier = threading.Barrier(3, timeout=5)
    done = []

    def fake_run_job(job_id, targets, *args):
        barrier.wait()
        done.append(job_id)

    monkeypatch.setattr(service, "run_job", fake_run_job)
    tasks = BackgroundTasks()
    launcher = service.JobLauncher(lambda: None, None, lambda: None)
    launcher.launch_parallel(tasks, [(1, FreshTargets(None)), (2, FreshTargets(None)), (3, FreshTargets(None))])
    launcher.launch_parallel(tasks, [])
    assert len(tasks.tasks) == 1
    tasks.tasks[0].func(*tasks.tasks[0].args)
    assert sorted(done) == [1, 2, 3]


def test_launcher_logs_exception_outside_job(monkeypatch, caplog):
    """ジョブの外で起きた例外(DB に接続できない等)は、並行実行のスレッドで消えずにログに残る。"""
    from smdx_api.proposals import service

    def broken_run_job(*args):
        raise RuntimeError("DB に接続できません")

    monkeypatch.setattr(service, "run_job", broken_run_job)
    launcher = service.JobLauncher(lambda: None, None, lambda: None)
    with caplog.at_level("ERROR", logger="smdx_api.proposals.service"):
        launcher._run_all([(7, FreshTargets(None))])
    assert "再計算ジョブ 7 を実行できませんでした" in caplog.text
    assert "DB に接続できません" in caplog.text
