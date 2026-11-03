"""今日の状況の集計(詳細設計書「今日の状況(GET /api/dashboard)の項目」)。

保存済みの提案・取込・気象から数えるだけで、計算や気象APIの呼び出しはしない。
JST の日付での比較は Python 側で範囲を作ってから SQL に渡す(DB のタイムゾーン設定に依存しない)。
"""
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from smdx_api.clock import JST
from smdx_api.db.models import (
    CalendarDay,
    Department,
    ImportLog,
    InventorySnapshot,
    Product,
    Promotion,
    Proposal,
    ProposalJob,
    WeatherForecast,
)
from smdx_api.proposals import inputs
from smdx_api.proposals.compute_fresh import business_hours
from smdx_api.proposals.jobs import JobKey
from smdx_api.proposals.schedule import deli_default_target
from smdx_api.proposals.service import is_production
from smdx_api.settings.values import AppSettings
from smdx_api.weather_client.codes import weather_label
from smdx_api.weather_client.store import day_range
from smdx_features.weather import jst_times, summarize

# 当日の期限に加えて、現在からこの時間以内の期限を数える(翌朝の製造開始などを前日のうちに見せる)
DEADLINE_WINDOW = timedelta(hours=24)

_STATUSES = ("pending", "approved", "confirmed", "expired")


@dataclass
class DeadlineGroup:
    department_code: str
    deadline: datetime
    target_date: date
    time_band: int | None
    counts: Counter = field(default_factory=Counter)
    bulk_approvable: int = 0
    warnings: Counter = field(default_factory=Counter)


@dataclass(frozen=True)
class TomorrowWeather:
    weather_code: int | None
    weather_label: str
    temperature: float | None
    temperature_min: float | None
    precipitation: float | None
    fetched_at: datetime


@dataclass(frozen=True)
class DataStatus:
    department_code: str
    pos_latest_date: date | None
    pos_imported_at: datetime | None
    inventory_based_at: datetime | None
    stale_pos: bool


def deadline_groups(db: Session, departments: Sequence[Department], now: datetime,
                    settings: AppSettings) -> list[DeadlineGroup]:
    """期限が当日のもの、または現在から24時間以内のものを「部門×期限×対象日×時間帯」でまとめる。"""
    if not departments:
        return []
    today = now.astimezone(JST).date()
    start, end_of_today = day_range(today, today)
    end = max(end_of_today, now + DEADLINE_WINDOW)
    codes = {d.id: d.code for d in departments}
    deli_ids = [d.id for d in departments if is_production(d)]
    q = select(Proposal).where(
        Proposal.department_id.in_(codes), Proposal.deadline >= start, Proposal.deadline < end,
        # 惣菜は製造計画の一覧と同じく、現在の区切りにある時間帯だけ
        or_(Proposal.department_id.not_in(deli_ids), Proposal.time_band.in_(settings.deli_time_bands)),
    )
    groups: dict[tuple, DeadlineGroup] = {}
    for p in db.scalars(q):
        key = (codes[p.department_id], p.deadline, p.target_date, p.time_band)
        g = groups.setdefault(key, DeadlineGroup(*key))
        g.counts[p.status] += 1
        if p.status == "pending":
            if p.warnings:
                g.warnings.update(p.warnings)
            else:
                g.bulk_approvable += 1
    return sorted(groups.values(), key=lambda g: (g.deadline, g.department_code, g.target_date, g.time_band or 0))


def status_counts(g: DeadlineGroup) -> dict[str, int]:
    return {s: g.counts.get(s, 0) for s in _STATUSES}


def last_finished_job(db: Session, department: Department, key: JobKey) -> ProposalJob | None:
    """既定表示のジョブ(key)のうち、最後に終わったもの。別の対象日を指定した再計算の成否は含めない。"""
    return db.scalar(select(ProposalJob).where(ProposalJob.department_id == department.id,
                                               ProposalJob.scope == key.scope, ProposalJob.target_date == key.target_date,
                                               ProposalJob.status != "running")
                     .order_by(ProposalJob.finished_at.desc().nulls_last(), ProposalJob.id.desc()).limit(1))


def tomorrow_weather(db: Session, day: date, settings: AppSettings) -> TomorrowWeather | None:
    """保存済みの予報のうち、その日の営業時間を含む最も新しい取得を、特徴量の日別の集約と同じ規則でまとめる。"""
    open_h, close_h = business_hours(settings)
    lo, hi = datetime.combine(day, time(open_h), JST), datetime.combine(day, time(0), JST) + timedelta(hours=close_h)
    fetched_at = db.scalar(
        select(WeatherForecast.fetched_at)
        .where(WeatherForecast.forecast_time >= lo, WeatherForecast.forecast_time < hi)
        .group_by(WeatherForecast.fetched_at)
        .having(func.count() >= close_h - open_h)
        .order_by(WeatherForecast.fetched_at.desc())
        .limit(1)
    )
    if fetched_at is None:
        return None
    rows = db.execute(
        select(WeatherForecast.forecast_time, WeatherForecast.weather_code, WeatherForecast.temperature,
               WeatherForecast.precipitation_probability, WeatherForecast.precipitation)
        .where(WeatherForecast.fetched_at == fetched_at, WeatherForecast.forecast_time >= lo,
               WeatherForecast.forecast_time < hi)
    )
    frame = pd.DataFrame([tuple(r) for r in rows], columns=inputs.WEATHER_COLUMNS)
    frame["time"] = jst_times(frame["time"])
    s = summarize(frame, day, open_h, close_h, "max")
    temps = frame["temperature"].dropna()
    return TomorrowWeather(s.weather_code, weather_label(s.weather_code), s.temperature,
                           None if temps.empty else float(temps.min()), s.precipitation, fetched_at)


def tomorrow_promotions(db: Session, departments: Sequence[Department], day: date) -> list[tuple[str, Product, Promotion]]:
    """その日を期間に含む、閲覧できる部門の特売・チラシ(部門コード・商品コードの順)。"""
    if not departments:
        return []
    by_id = {d.id: d for d in departments}
    rows = db.execute(
        select(Promotion, Product).join(Product, Product.id == Promotion.product_id)
        .where(Product.department_id.in_(by_id), Promotion.start_date <= day, Promotion.end_date >= day)
    )
    out = [(by_id[product.department_id], product, promo) for promo, product in rows]
    out.sort(key=lambda x: (x[0].code, x[1].product_code, x[2].start_date, x[2].id))
    return [(d.name, product, promo) for d, product, promo in out]


def calendar_of(db: Session, day: date) -> list[CalendarDay]:
    return list(db.scalars(select(CalendarDay).where(CalendarDay.date == day).order_by(CalendarDay.kind, CalendarDay.id)))


def expected_pos_date(department: Department, now: datetime, settings: AppSettings) -> date:
    """既定表示の提案に付ける STALE_POS の基準日(この日までの POS がそろっていなければ古い)。

    生鮮は発注日(未来の発注日は当日)の前日、惣菜は計画日(対象日 − 1。未来の計画日は当日)の前日。
    """
    today = now.astimezone(JST).date()
    if is_production(department):
        plan_date = deli_default_target(now, settings) - timedelta(days=1)
        return min(plan_date, today) - timedelta(days=1)
    return today - timedelta(days=1)


def data_status(db: Session, department: Department, now: datetime, settings: AppSettings) -> DataStatus:
    latest_pos = inputs.latest_pos_date(db, department.id)
    imported_at = db.scalar(select(func.max(ImportLog.finished_at)).where(
        ImportLog.department_id == department.id, ImportLog.kind == "pos"))
    based_at = None
    if not is_production(department):
        based_at = db.scalar(
            select(func.max(InventorySnapshot.based_at)).join(Product, Product.id == InventorySnapshot.product_id)
            .where(Product.department_id == department.id, InventorySnapshot.based_at <= now))
    stale = latest_pos is None or latest_pos < expected_pos_date(department, now, settings)
    return DataStatus(department.code, latest_pos, imported_at, based_at, stale)
