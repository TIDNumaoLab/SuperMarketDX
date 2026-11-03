"""再計算ジョブ(詳細設計書「二重実行防止」)。

同じ部門×種別×対象日(既定表示では発注日、対象日の指定では納品日)で実行中のジョブがあれば新たに開始せず、そのジョブを返す。
開始は部門の行をロック(FOR NO KEY UPDATE。部門を参照する行の追加は妨げない)してから行い、同時に一覧を開いても
1件しか作らない。10分を超えた実行中のジョブは失敗とみなし、裏の処理が後で終わっても失敗のままにする(計算した提案は保存する)。
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from smdx_api.db.models import Department, ProposalJob
from smdx_api.proposals.compute_deli import compute_deli
from smdx_api.proposals.compute_fresh import ComputeServices, FreshTargets, compute_fresh
from smdx_api.proposals.deadlines import apply_deadlines
from smdx_api.proposals.persist import apply_computed
from smdx_api.settings.service import load_settings

log = logging.getLogger(__name__)

JOB_TIMEOUT = timedelta(minutes=10)
TIMED_OUT = "タイムアウトしました"
JOB_FAILED = "計算中にエラーが発生しました。時間をおいて再計算してください"


@dataclass(frozen=True)
class JobKey:
    """ジョブを区別する種別と日付。同じ日付でも、発注日(既定表示)と納品日(対象日の指定)では計算する提案が違う。"""
    scope: Literal["default", "date"]
    target_date: date


def start_or_get_job(db: Session, department: Department, key: JobKey, now: datetime, total: int) -> tuple[ProposalJob, bool]:
    """実行中のジョブを返すか、新しく開始する。2つ目の戻り値は新しく開始したか。commit する。"""
    db.execute(select(Department.id).where(Department.id == department.id).with_for_update(key_share=True))
    running = list(db.scalars(
        select(ProposalJob).where(ProposalJob.department_id == department.id, ProposalJob.scope == key.scope,
                                  ProposalJob.target_date == key.target_date, ProposalJob.status == "running")
        .order_by(ProposalJob.started_at.desc())
    ))
    active = next((j for j in running if j.started_at >= now - JOB_TIMEOUT), None)
    if active is not None:
        db.commit()
        return active, False
    for j in running:
        j.status, j.error, j.finished_at = "failed", TIMED_OUT, now
    job = ProposalJob(department_id=department.id, scope=key.scope, target_date=key.target_date, status="running",
                      processed=0, total=total, started_at=now)
    db.add(job)
    db.commit()
    return job, True


def running_job(db: Session, department: Department, key: JobKey, now: datetime) -> ProposalJob | None:
    """部門×種別×対象日で実行中(10分以内に開始)のジョブ。"""
    return db.scalar(select(ProposalJob).where(
        ProposalJob.department_id == department.id, ProposalJob.scope == key.scope,
        ProposalJob.target_date == key.target_date, ProposalJob.status == "running",
        ProposalJob.started_at >= now - JOB_TIMEOUT,
    ).order_by(ProposalJob.started_at.desc()).limit(1))


def run_job(
    job_id: int,
    targets: FreshTargets,
    session_factory: sessionmaker | Callable[[], Session],
    services: ComputeServices,
    now_fn: Callable[[], datetime],
    clock: Callable[[], datetime] | None = None,
) -> None:
    """新しいセッションで計算・保存する。進捗は1件保存するたびに更新する。例外は外に出さずジョブの失敗にする。

    now_fn は計算日時(要求を受けた時刻)、clock は終了日時を記録する時計(省略時は now_fn)。
    """
    clock = clock or now_fn
    with session_factory() as db:
        job = db.get(ProposalJob, job_id)
        try:
            department = db.get(Department, job.department_id)
            now = now_fn()
            # 期限経過の更新は先に確定し、その行のロックを持ったまま気象の取得・予測をしない
            apply_deadlines(db, now, department.id)
            db.commit()
            settings = load_settings(db)
            if department.business_type == "production":
                # 惣菜は対象日を決めてから開始する(service.resolved_targets)
                computed, notice = compute_deli(db, department, now, settings, services, targets.explicit_date)
            else:
                computed, notice = compute_fresh(db, department, now, settings, services, targets)
            job.total, job.notice = len(computed), notice
            db.commit()

            def progress(n: int) -> None:
                job.processed = n
                db.commit()

            apply_computed(db, department, computed, now, on_progress=progress)
            _finish(db, job_id, "succeeded", None, clock())
        except Exception:
            # 例外の文言(SQL など)は画面に出さず、ログにだけ残す
            log.exception("提案の再計算ジョブが失敗しました: job_id=%s", job_id)
            db.rollback()
            _finish(db, job_id, "failed", JOB_FAILED, clock())


def _finish(db: Session, job_id: int, status: str, error: str | None, finished_at: datetime) -> None:
    """実行中のままのジョブだけを終了にする(タイムアウトで失敗にしたジョブを上書きしない)。"""
    db.execute(update(ProposalJob).where(ProposalJob.id == job_id, ProposalJob.status == "running")
               .values(status=status, error=error, finished_at=finished_at))
    db.commit()
