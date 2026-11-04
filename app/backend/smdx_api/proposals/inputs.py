"""提案計算の入力を DB から集める(在庫・発注残・販売実績・カレンダー・特売・気象・最新性判定の材料)。

JST の日付での比較は Python 側で範囲を作ってから SQL に渡す(DB のタイムゾーン設定に依存しない)。
"""
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from smdx_api.clock import JST
from smdx_api.db.models import (
    CalendarDay,
    DisplayStockEntry,
    ImportLog,
    InventorySnapshot,
    PosSale,
    Product,
    Promotion,
    Proposal,
    ProposalHistory,
)
from smdx_api.proposals.rules import FreshnessContext
from smdx_api.settings.service import EVENTS_CHANGED_KEY, SETTINGS_CHANGED_KEY, read_internal_datetime
from smdx_api.weather_client.service import ForecastResult
from smdx_features.build import CalendarData

# 実績の取得期間(対象日から遡る日数)。前週同曜日・7日平均・売上構成比の8週間を満たす
HISTORY_DAYS = 70

DAILY_COLUMNS = ["product_code", "sales_date", "quantity"]
HOURLY_COLUMNS = ["product_code", "sales_date", "sales_hour", "quantity"]
WEATHER_COLUMNS = ["time", "weather_code", "temperature", "precipitation_probability", "precipitation"]


def latest_inventory_today(db: Session, product_ids: Sequence[int], now: datetime) -> dict[int, tuple[int, datetime]]:
    """商品ごとの、当日(JST)0:00〜now の在庫のうち based_at が最も新しいもの。無い商品はキー無し。"""
    local = now.astimezone(JST)
    start = datetime.combine(local.date(), time(0), JST)
    rows = db.execute(
        select(InventorySnapshot.product_id, InventorySnapshot.quantity, InventorySnapshot.based_at)
        .where(InventorySnapshot.product_id.in_(product_ids), InventorySnapshot.based_at >= start,
               InventorySnapshot.based_at <= now)
        .distinct(InventorySnapshot.product_id)
        .order_by(InventorySnapshot.product_id, InventorySnapshot.based_at.desc())
    )
    return {pid: (qty, based_at.astimezone(JST)) for pid, qty, based_at in rows}


def confirmed_orders(db: Session, product_ids: Sequence[int], since: date, until: date) -> dict[int, list[tuple[date, int]]]:
    """商品ごとの、納品日が since〜until(until を含まない)の確定した提案(納品日, 数量)。発注残の集計に使う。"""
    rows = db.execute(
        select(Proposal.product_id, Proposal.target_date, Proposal.proposed_qty).where(
            Proposal.product_id.in_(product_ids), Proposal.status == "confirmed", Proposal.target_date < until,
            Proposal.target_date >= since,
        )
    )
    out: dict[int, list[tuple[date, int]]] = {}
    for pid, d, qty in rows:
        out.setdefault(pid, []).append((d, qty))
    return out


def backlog_qty(orders: Sequence[tuple[date, int]], inventory_based_at: datetime, target: date, delivery_time: time) -> int:
    """発注残: 確定した提案のうち、納品日時が在庫基準日時より後で、納品日が対象の納品日より前のものの数量の合計。"""
    return sum(qty for d, qty in orders
               if d < target and datetime.combine(d, delivery_time, JST) > inventory_based_at)


def daily_sales_frame(db: Session, product_ids: Sequence[int], since: date) -> pd.DataFrame:
    """日ごとの販売数(日計と時刻つきを合計)。"""
    rows = db.execute(
        select(Product.product_code, PosSale.sales_date, func.sum(PosSale.quantity))
        .join(Product, Product.id == PosSale.product_id)
        .where(PosSale.product_id.in_(product_ids), PosSale.sales_date >= since)
        .group_by(Product.product_code, PosSale.sales_date)
    )
    return pd.DataFrame([tuple(r) for r in rows], columns=DAILY_COLUMNS)


def hourly_sales_rows(db: Session, product_ids: Sequence[int], since: date) -> dict[int, list[tuple[date, int, float]]]:
    """商品ごとの時刻つきの POS(販売日, 時, 数量)。売上構成比に使う。"""
    rows = db.execute(
        select(PosSale.product_id, PosSale.sales_date, PosSale.sales_hour, PosSale.quantity)
        .where(PosSale.product_id.in_(product_ids), PosSale.sales_date >= since, PosSale.sales_hour.is_not(None))
        .order_by(PosSale.product_id, PosSale.sales_date, PosSale.sales_hour)
    )
    out: dict[int, list[tuple[date, int, float]]] = {}
    for pid, d, h, q in rows:
        out.setdefault(pid, []).append((d, int(h), float(q)))
    return out


def hourly_sales_frame(db: Session, product_ids: Sequence[int], since: date) -> pd.DataFrame:
    rows = db.execute(
        select(Product.product_code, PosSale.sales_date, PosSale.sales_hour, PosSale.quantity)
        .join(Product, Product.id == PosSale.product_id)
        .where(PosSale.product_id.in_(product_ids), PosSale.sales_date >= since, PosSale.sales_hour.is_not(None))
    )
    return pd.DataFrame([tuple(r) for r in rows], columns=HOURLY_COLUMNS)


def _department_pos(department_id: int):
    return select(PosSale.sales_date).join(Product, Product.id == PosSale.product_id).where(
        Product.department_id == department_id)


def latest_pos_date(db: Session, department_id: int) -> date | None:
    """部門の POS が取り込まれている最新の販売日。"""
    sub = _department_pos(department_id).subquery()
    return db.scalar(select(func.max(sub.c.sales_date)))


def missing_pos_days(db: Session, department_id: int, start: date, end: date) -> set[date]:
    """start〜end のうち、部門の POS が1行も無い日(未取込日)。"""
    q = _department_pos(department_id).where(PosSale.sales_date >= start, PosSale.sales_date <= end).distinct()
    present = set(db.scalars(q))
    return {start + timedelta(days=i) for i in range((end - start).days + 1)} - present


def calendar_data(db: Session, start: date, end: date) -> CalendarData:
    rows = db.execute(
        select(CalendarDay.date, CalendarDay.kind, CalendarDay.name).where(CalendarDay.date >= start, CalendarDay.date <= end)
    )
    holidays, events = {}, {}
    for d, kind, name in rows:
        (holidays if kind == "holiday" else events)[d] = name
    return CalendarData(holidays, events)


def promotions_frame(db: Session, product_ids: Sequence[int], start: date, end: date) -> pd.DataFrame:
    """期間に重なる特売・チラシ。"""
    rows = db.execute(
        select(Product.product_code, Promotion.start_date, Promotion.end_date)
        .join(Product, Product.id == Promotion.product_id)
        .where(Promotion.product_id.in_(product_ids), Promotion.start_date <= end, Promotion.end_date >= start)
    )
    return pd.DataFrame([tuple(r) for r in rows], columns=["product_code", "start_date", "end_date"])


def weather_frame(result: ForecastResult) -> pd.DataFrame | None:
    """予報を特徴量パッケージの形の表にする。取得できなかった場合は None(全行欠損)。"""
    if not result.available:
        return None
    return pd.DataFrame(
        [(r.time.astimezone(JST), r.weather_code, r.temperature, r.precipitation_probability, r.precipitation)
         for r in result.rows],
        columns=WEATHER_COLUMNS,
    )


def freshness_context(db: Session, department_id: int, current_model_version: str, stale_hours: float) -> FreshnessContext:
    """最新性判定の材料。data_changed_at は、その部門の在庫・POSの取込、商品マスタの取込(全部門に効く)、在庫の手入力、
    陳列残数の入力、提案の確定(発注残の変化)のうち最も新しい日時。

    手入力の在庫・陳列残数は行の更新日時(DB の時計)を使う。同じ基準日時で入力し直すと行が上書きされるため。
    """
    product_ids = select(Product.id).where(Product.department_id == department_id)
    candidates = [
        db.scalar(select(func.max(ImportLog.finished_at)).where(
            ImportLog.department_id == department_id, ImportLog.kind.in_(("pos", "inventory")))),
        # 発注単位・持越可否などの変更を反映する(商品マスタの取込は部門を持たない)
        db.scalar(select(func.max(ImportLog.finished_at)).where(ImportLog.kind == "products")),
        db.scalar(select(func.max(InventorySnapshot.updated_at)).where(
            InventorySnapshot.source == "manual", InventorySnapshot.product_id.in_(product_ids))),
        db.scalar(select(func.max(DisplayStockEntry.updated_at)).where(DisplayStockEntry.product_id.in_(product_ids))),
        db.scalar(select(func.max(ProposalHistory.occurred_at))
                  .join(Proposal, Proposal.id == ProposalHistory.proposal_id)
                  .where(ProposalHistory.action == "confirm", Proposal.department_id == department_id)),
    ]
    found = [c for c in candidates if c is not None]
    return FreshnessContext(
        data_changed_at=max(found) if found else None,
        events_changed_at=read_internal_datetime(db, EVENTS_CHANGED_KEY),
        settings_changed_at=read_internal_datetime(db, SETTINGS_CHANGED_KEY),
        current_model_version=current_model_version,
        stale_hours=stale_hours,
    )
