"""提案一覧・手動再計算・ジョブ進捗(F-08、F-10)。"""
from collections.abc import Sequence
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from smdx_api.api.deps import (
    NOT_FOUND,
    current_user,
    department_for,
    get_compute_services,
    get_db,
    get_job_launcher,
)
from smdx_api.auth.permissions import Principal
from smdx_api.clock import JST, get_now
from smdx_api.db.models import Department, Product, Proposal, ProposalJob, User
from smdx_api.proposals import actions
from smdx_api.proposals.actions import ProposalNotFound
from smdx_api.proposals.basis import BASIS_KEYS
from smdx_api.proposals.compute_fresh import ComputeServices, FreshTargets, department_products, fresh_target_dates
from smdx_api.proposals.deadlines import apply_deadlines
from smdx_api.proposals.jobs import JOB_TIMEOUT, TIMED_OUT, JobKey, start_or_get_job
from smdx_api.proposals.rules import InputError, StateError
from smdx_api.proposals.schedule import TargetOutOfRange, check_target_range
from smdx_api.proposals.service import (
    JobLauncher,
    deli_target,
    is_production,
    job_key,
    resolved_targets,
    start_auto_recalc,
    wanted,
)
from smdx_api.schemas.proposals import (
    AdjustIn,
    ApproveIn,
    BulkApproveIn,
    BulkApproveOut,
    FreshnessOut,
    JobOut,
    JobResponse,
    ProposalListOut,
    ProposalOut,
    RecalculateIn,
    SkippedOut,
    StatusFilter,
)
from smdx_api.settings.service import load_settings

router = APIRouter(prefix="/api/proposals")

def parse_targets(target_date: date | None, now: datetime) -> FreshTargets:
    if target_date is not None:
        try:
            check_target_range(target_date, now.astimezone(JST).date())
        except TargetOutOfRange as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
    return FreshTargets(target_date)


def proposals_out(db: Session, proposals: Sequence[Proposal]) -> list[ProposalOut]:
    """提案を応答の形にする(商品・部門・承認者の名前を引き、根拠を平坦に並べる)。"""
    if not proposals:
        return []
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_({x.product_id for x in proposals})))}
    departments = {d.id: d.code for d in db.scalars(select(Department))}
    approver_ids = {x.approved_by for x in proposals if x.approved_by is not None}
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(approver_ids)))} if approver_ids else {}
    out = []
    for x in proposals:
        product = products[x.product_id]
        basis = {k: (x.basis or {}).get(k) for k in BASIS_KEYS}
        out.append(ProposalOut(
            id=x.id, department_code=departments[x.department_id], product_code=product.product_code,
            product_name=product.name, target_date=x.target_date, time_band=x.time_band, proposed_qty=x.proposed_qty,
            original_qty=x.original_qty, recalculated_qty=x.recalculated_qty, is_adjusted=x.is_adjusted,
            adjust_reason=x.adjust_reason, adjust_note=x.adjust_note, status=x.status, deadline=x.deadline,
            approved_by=x.approved_by, approved_by_name=names.get(x.approved_by), approved_at=x.approved_at,
            warnings=list(x.warnings or []), order_unit=product.order_unit, calculated_at=x.calculated_at,
            created_at=x.created_at, updated_at=x.updated_at, **basis,
        ))
    return out


def _parse(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _freshness(proposals: Sequence[Proposal]) -> FreshnessOut:
    def latest(values):
        values = [v for v in values if v is not None]
        return max(values) if values else None

    return FreshnessOut(
        calculated_at=latest(p.calculated_at for p in proposals),
        weather_fetched_at=latest(_parse((p.basis or {}).get("weather_fetched_at")) for p in proposals),
        inventory_based_at=latest(_parse((p.basis or {}).get("inventory_based_at")) for p in proposals),
    )


def job_out(job: ProposalJob) -> JobOut:
    return JobOut(id=job.id, status=job.status, processed=job.processed, total=job.total, error=job.error,
                  notice=job.notice)


def _jobs(department: Department, key: JobKey):
    return select(ProposalJob).where(ProposalJob.department_id == department.id, ProposalJob.scope == key.scope,
                                     ProposalJob.target_date == key.target_date)


def _last_notice(db: Session, department: Department, key: JobKey) -> str | None:
    """同じ部門・種別・対象日で最後に成功したジョブの注記。"""
    job = db.scalar(_jobs(department, key).where(ProposalJob.status == "succeeded")
                    .order_by(ProposalJob.started_at.desc(), ProposalJob.id.desc()).limit(1))
    return job.notice if job else None


def _shown(db: Session, department: Department, now: datetime, settings, targets: FreshTargets,
           status: str | None) -> list[Proposal]:
    q = select(Proposal).join(Product, Product.id == Proposal.product_id).where(Proposal.department_id == department.id)
    if is_production(department):
        # 対象日の全時間帯(製造開始を過ぎたものも含む)。区切りを変えた後の古い時間帯の提案は出さない
        q = q.where(Proposal.target_date == deli_target(now, settings, targets),
                    Proposal.time_band.in_(settings.deli_time_bands))
    elif targets.explicit_date is not None:
        q = q.where(Proposal.target_date == targets.explicit_date)
    else:
        # 既定表示は各商品の最も早い納品日の提案だけ
        pairs = list(fresh_target_dates(department_products(db, department), now, settings, targets).items())
        if not pairs:
            return []
        q = q.where(tuple_(Proposal.product_id, Proposal.target_date).in_(pairs))
    if status is not None:
        q = q.where(Proposal.status == status)
    return list(db.scalars(q.order_by(Product.product_code, Proposal.time_band)))


@router.get("", response_model=ProposalListOut)
def list_proposals(
    background_tasks: BackgroundTasks,
    department_code: str,
    target_date: date | None = None,
    status: StatusFilter | None = None,
    p: Principal = Depends(current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    services: ComputeServices = Depends(get_compute_services),
    launcher: JobLauncher = Depends(get_job_launcher),
) -> ProposalListOut:
    """既存の提案をすぐに返し、再計算が必要ならジョブを開始して併せて返す(詳細設計書「きっかけ」)。"""
    department = department_for(department_code, p, db)
    targets = parse_targets(target_date, now)
    apply_deadlines(db, now, department.id)
    db.commit()
    settings = load_settings(db)
    key = job_key(department, now, settings, targets)
    job = start_auto_recalc(db, department, now, settings, services, targets,
                            lambda job_id, t: launcher.launch(background_tasks, job_id, t))
    shown = _shown(db, department, now, settings, targets, status)
    shown_date = deli_target(now, settings, targets) if is_production(department) else targets.explicit_date
    return ProposalListOut(proposals=proposals_out(db, shown), target_date=shown_date, freshness=_freshness(shown),
                           job=job_out(job) if job else None, notice=_last_notice(db, department, key))


@router.post("/recalculate", response_model=JobResponse)
def recalculate(
    body: RecalculateIn,
    background_tasks: BackgroundTasks,
    p: Principal = Depends(current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    launcher: JobLauncher = Depends(get_job_launcher),
) -> JobResponse:
    """手動再計算。判定を省略して開始する(実行中があればそれを返す)。"""
    department = department_for(body.department_code, p, db)
    targets = parse_targets(body.target_date, now)
    settings = load_settings(db)
    total = len(wanted(db, department, now, settings, targets))
    job, created = start_or_get_job(db, department, job_key(department, now, settings, targets), now, total)
    if created:
        launcher.launch(background_tasks, job.id, resolved_targets(department, now, settings, targets))
    return JobResponse(job=job_out(job))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, p: Principal = Depends(current_user), db: Session = Depends(get_db),
            now: datetime = Depends(get_now)) -> JobOut:
    job = db.get(ProposalJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    department_for(db.get(Department, job.department_id).code, p, db)
    # 再起動などで止まった実行中のジョブは、10分を超えたら失敗とする(画面が待ち続けないように)
    if job.status == "running" and job.started_at < now - JOB_TIMEOUT:
        job.status, job.error, job.finished_at = "failed", TIMED_OUT, now
        db.commit()
    return job_out(job)


def _check_access(db: Session, proposal_id: int, p: Principal) -> None:
    """提案の部門を操作できるか(不在は 404、他部門は 403)。"""
    row = db.get(Proposal, proposal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    department_for(db.get(Department, row.department_id).code, p, db)


def _act(db: Session, fn, *args) -> ProposalOut:
    """操作を行う。条件違反でも、操作の冒頭で行った期限経過の更新は確定する(操作は条件を確かめてから提案を変える)。"""
    try:
        row = fn(db, *args)
    except ProposalNotFound:
        db.rollback()
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    except StateError as e:
        db.commit()
        raise HTTPException(status_code=409, detail=e.message) from None
    except InputError as e:
        db.commit()
        raise HTTPException(status_code=422, detail=e.message) from None
    db.commit()
    db.refresh(row)
    return proposals_out(db, [row])[0]


@router.patch("/{proposal_id}", response_model=ProposalOut)
def adjust_proposal(proposal_id: int, body: AdjustIn, p: Principal = Depends(current_user),
                    db: Session = Depends(get_db), now: datetime = Depends(get_now)) -> ProposalOut:
    _check_access(db, proposal_id, p)
    return _act(db, actions.adjust, proposal_id, body.quantity, body.reason, body.reason_note, p.user_id, now)


@router.post("/approve-bulk", response_model=BulkApproveOut)
def approve_bulk(body: BulkApproveIn, p: Principal = Depends(current_user), db: Session = Depends(get_db),
                 now: datetime = Depends(get_now)) -> BulkApproveOut:
    """他部門の提案が1件でも含まれていれば、何も承認せず全体を 403 にする。"""
    rows = db.scalars(select(Proposal).where(Proposal.id.in_([i.id for i in body.items])))
    for code in {db.get(Department, r.department_id).code for r in rows}:
        department_for(code, p, db)
    approved, skipped = actions.approve_bulk(db, [(i.id, i.expected_qty) for i in body.items], p.user_id, now)
    db.commit()
    return BulkApproveOut(approved_ids=approved, skipped=[SkippedOut(id=i, reason=r) for i, r in skipped])


@router.post("/{proposal_id}/approve", response_model=ProposalOut)
def approve_proposal(proposal_id: int, body: ApproveIn, p: Principal = Depends(current_user),
                     db: Session = Depends(get_db), now: datetime = Depends(get_now)) -> ProposalOut:
    _check_access(db, proposal_id, p)
    return _act(db, actions.approve, proposal_id, body.expected_qty, body.confirm_warnings, p.user_id, now)


@router.post("/{proposal_id}/cancel-approval", response_model=ProposalOut)
def cancel_approval(proposal_id: int, p: Principal = Depends(current_user), db: Session = Depends(get_db),
                    now: datetime = Depends(get_now)) -> ProposalOut:
    _check_access(db, proposal_id, p)
    return _act(db, actions.cancel_approval, proposal_id, p.user_id, now)


@router.post("/{proposal_id}/adopt-recalculated", response_model=ProposalOut)
def adopt_recalculated(proposal_id: int, p: Principal = Depends(current_user), db: Session = Depends(get_db),
                       now: datetime = Depends(get_now)) -> ProposalOut:
    _check_access(db, proposal_id, p)
    return _act(db, actions.adopt_recalculated, proposal_id, p.user_id, now)
