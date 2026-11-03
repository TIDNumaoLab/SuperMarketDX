"""今日の状況(F-21)。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.api.deps import current_user, get_compute_services, get_db, get_job_launcher
from smdx_api.api.routes_proposals import job_out
from smdx_api.auth.permissions import Principal, can_access_department
from smdx_api.clock import JST, get_now
from smdx_api.db.models import Department
from smdx_api.proposals import dashboard
from smdx_api.proposals.compute_fresh import ComputeServices, FreshTargets
from smdx_api.proposals.deadlines import apply_deadlines
from smdx_api.proposals.service import JobLauncher, job_key, start_auto_recalc
from smdx_api.schemas.dashboard import (
    CalendarEntryOut,
    DashboardDepartmentOut,
    BusinessHoursOut,
    DashboardOut,
    DataStatusOut,
    DeadlineOut,
    LastJobOut,
    TomorrowOut,
    TomorrowPromotionOut,
    TomorrowWeatherOut,
    WarningCountOut,
)
from smdx_api.settings.service import load_settings

router = APIRouter(prefix="/api/dashboard")


@router.get("", response_model=DashboardOut)
def get_dashboard(
    background_tasks: BackgroundTasks,
    p: Principal = Depends(current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    services: ComputeServices = Depends(get_compute_services),
    launcher: JobLauncher = Depends(get_job_launcher),
) -> DashboardOut:
    """閲覧できる各部門の既定表示について再計算を始め、保存済みの提案から集計して返す(ジョブの終了は待たない)。"""
    departments = [d for d in db.scalars(select(Department).order_by(Department.code))
                   if can_access_department(p, d.code)]
    for d in departments:
        apply_deadlines(db, now, d.id)
    db.commit()
    settings = load_settings(db)

    department_out = []
    # 開始したジョブは部門ごとに並行して実行する(店長は全部門を同時に計算する)
    started: list[tuple[int, FreshTargets]] = []
    for d in departments:
        job = start_auto_recalc(db, d, now, settings, services, FreshTargets(None),
                                lambda job_id, t: started.append((job_id, t)))
        last = dashboard.last_finished_job(db, d, job_key(d, now, settings, FreshTargets(None)))
        department_out.append(DashboardDepartmentOut(
            department_code=d.code, department_name=d.name, business_type=d.business_type,
            job=job_out(job) if job else None,
            last_job=LastJobOut(status=last.status, finished_at=last.finished_at, error=last.error) if last else None,
        ))
    launcher.launch_parallel(background_tasks, started)

    deadlines = [
        DeadlineOut(department_code=g.department_code, deadline=g.deadline, target_date=g.target_date,
                    time_band=g.time_band, bulk_approvable=g.bulk_approvable,
                    warnings=[WarningCountOut(code=c, count=n) for c, n in sorted(g.warnings.items())],
                    **dashboard.status_counts(g))
        for g in dashboard.deadline_groups(db, departments, now, settings)
    ]

    tomorrow = now.astimezone(JST).date() + timedelta(days=1)
    weather = dashboard.tomorrow_weather(db, tomorrow, settings)
    tomorrow_out = TomorrowOut(
        date=tomorrow,
        weather=TomorrowWeatherOut(**vars(weather)) if weather else None,
        promotions=[TomorrowPromotionOut(department_name=name, product_name=product.name, start_date=promo.start_date,
                                         end_date=promo.end_date, description=promo.description)
                    for name, product, promo in dashboard.tomorrow_promotions(db, departments, tomorrow)],
        calendar=[CalendarEntryOut(kind=c.kind, name=c.name) for c in dashboard.calendar_of(db, tomorrow)],
    )
    status = [DataStatusOut(**vars(dashboard.data_status(db, d, now, settings))) for d in departments]
    hours = BusinessHoursOut(open=settings.business_open.strftime("%H:%M"), close=settings.business_close.strftime("%H:%M"))
    return DashboardOut(now=now, business_hours=hours, departments=department_out, deadlines=deadlines,
                        tomorrow=tomorrow_out, data_status=status)
