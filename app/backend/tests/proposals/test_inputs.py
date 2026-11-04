"""提案計算の入力の収集(詳細設計書「発注数・製造数の計算(生鮮)」「自動再計算の対象と判定」)。"""
from datetime import date, time

import pytest
from sqlalchemy import select, text

from smdx_api.db.models import (
    CalendarDay,
    Department,
    DisplayStockEntry,
    ImportLog,
    InventorySnapshot,
    ProposalHistory,
    Promotion,
)
from smdx_api.proposals.inputs import (
    backlog_qty,
    calendar_data,
    confirmed_orders,
    daily_sales_frame,
    freshness_context,
    hourly_sales_frame,
    hourly_sales_rows,
    latest_inventory_today,
    latest_pos_date,
    missing_pos_days,
    promotions_frame,
    weather_frame,
)
from smdx_api.settings.service import EVENTS_CHANGED_KEY, SETTINGS_CHANGED_KEY, touch_internal
from smdx_api.weather_client.service import ForecastResult
from tests.conftest import jst
from tests.fakes import hourly_rows


def dept(db, code):
    return db.scalar(select(Department).where(Department.code == code))


@pytest.mark.db
def test_latest_inventory_today_ignores_yesterday_and_future(db, product_factory, add_inventory, fixed_now):
    p = product_factory(code="VEG-001")  # fixed_now = 2026-10-16 10:00 JST
    add_inventory(p, jst(2026, 10, 15, 20), 9)
    add_inventory(p, jst(2026, 10, 16, 8), 5)
    add_inventory(p, jst(2026, 10, 16, 9, 30), 4)
    add_inventory(p, jst(2026, 10, 16, 12), 1)   # 未来
    other = product_factory(code="VEG-002")
    add_inventory(other, jst(2026, 10, 15, 20), 3)  # 前日分しか無い商品はキー無し
    assert latest_inventory_today(db, [p.id, other.id], fixed_now.value) == {p.id: (4, jst(2026, 10, 16, 9, 30))}


@pytest.mark.db
def test_latest_inventory_jst_midnight(db, product_factory, add_inventory):
    p = product_factory()
    add_inventory(p, jst(2026, 10, 15, 23, 50), 7)  # JST では前日
    add_inventory(p, jst(2026, 10, 16, 0, 10), 3)
    assert latest_inventory_today(db, [p.id], jst(2026, 10, 16, 0, 30)) == {p.id: (3, jst(2026, 10, 16, 0, 10))}
    assert latest_inventory_today(db, [p.id], jst(2026, 10, 16, 0, 5)) == {}


@pytest.mark.db
def test_backlog_counts_confirmed_before_target_after_inventory(db, product_factory, proposal_factory):
    p = product_factory()
    proposal_factory(p, target=date(2026, 10, 17), qty=12, status="confirmed")  # 納品 10/17 10:00 > 在庫 10/16 19:30
    proposal_factory(p, target=date(2026, 10, 16), qty=99, status="confirmed")  # 納品 10/16 10:00 は在庫基準より前
    proposal_factory(p, target=date(2026, 10, 18), qty=50, status="confirmed")  # 対象日と同日以降は含めない
    other = product_factory(code="VEG-002")
    proposal_factory(other, target=date(2026, 10, 17), qty=7, status="confirmed")  # 別商品
    proposal_factory(p, target=date(2026, 10, 15), qty=3, status="approved")     # 確定でない
    orders = confirmed_orders(db, [p.id], date(2026, 10, 16), date(2026, 10, 18))
    assert backlog_qty(orders[p.id], jst(2026, 10, 16, 19, 30), date(2026, 10, 18), time(10)) == 12
    assert set(orders) == {p.id}   # 別商品・対象日以降・確定でないものは読まない


@pytest.mark.db
def test_backlog_delivery_same_day_after_inventory(db, product_factory, proposal_factory):
    # 在庫基準が当日の開店前(8:00)なら、当日 10:00 納品の確定分は発注残に入る
    p = product_factory()
    proposal_factory(p, target=date(2026, 10, 16), qty=6, status="confirmed")
    orders = confirmed_orders(db, [p.id], date(2026, 10, 16), date(2026, 10, 17))
    assert backlog_qty(orders[p.id], jst(2026, 10, 16, 8), date(2026, 10, 17), time(10)) == 6


@pytest.mark.db
def test_freshness_context_takes_latest_change(db, product_factory, proposal_factory):
    veg, fish = dept(db, "VEG"), dept(db, "FISH")
    p = product_factory(code="VEG-001")
    db.add(ImportLog(kind="pos", department_id=veg.id, file_name="a.csv", imported_count=1, skipped_count=0,
                     errors=[], finished_at=jst(2026, 10, 16, 9)))
    db.add(ImportLog(kind="pos", department_id=fish.id, file_name="b.csv", imported_count=1, skipped_count=0,
                     errors=[], finished_at=jst(2026, 10, 16, 15)))   # 他部門は含めない
    db.add(ImportLog(kind="waste", department_id=veg.id, file_name="c.csv", imported_count=1, skipped_count=0,
                     errors=[], finished_at=jst(2026, 10, 16, 14)))   # 廃棄の取込は含めない
    db.add(InventorySnapshot(based_at=jst(2026, 10, 16, 8), product_id=p.id, quantity=1, source="manual",
                             updated_at=jst(2026, 10, 16, 10)))
    db.add(InventorySnapshot(based_at=jst(2026, 10, 16, 7), product_id=p.id, quantity=1, source="csv",
                             updated_at=jst(2026, 10, 16, 13)))      # CSV の在庫は取込履歴で数える
    pr = proposal_factory(p, status="confirmed")
    db.add(ProposalHistory(proposal_id=pr.id, action="confirm", occurred_at=jst(2026, 10, 16, 11)))
    db.add(ProposalHistory(proposal_id=pr.id, action="approve", occurred_at=jst(2026, 10, 16, 12)))
    db.flush()
    ctx = freshness_context(db, veg.id, "baseline", 3)
    assert ctx.data_changed_at == jst(2026, 10, 16, 11)
    assert ctx.events_changed_at is None and ctx.current_model_version == "baseline" and ctx.stale_hours == 3

    touch_internal(db, EVENTS_CHANGED_KEY, jst(2026, 10, 16, 12))
    assert freshness_context(db, veg.id, "baseline", 3).events_changed_at == jst(2026, 10, 16, 12)
    assert ctx.settings_changed_at is None
    touch_internal(db, SETTINGS_CHANGED_KEY, jst(2026, 10, 16, 13))
    assert freshness_context(db, veg.id, "baseline", 3).settings_changed_at == jst(2026, 10, 16, 13)


@pytest.mark.db
def test_freshness_context_counts_display_stock(db, product_factory):
    deli = dept(db, "DELI")
    p = product_factory(department="DELI")
    db.add(DisplayStockEntry(target_date=date(2026, 10, 16), entered_at=jst(2026, 10, 16, 12), product_id=p.id,
                             quantity=2, updated_at=jst(2026, 10, 16, 12, 1)))
    db.flush()
    assert freshness_context(db, deli.id, "baseline", 3).data_changed_at == jst(2026, 10, 16, 12, 1)
    assert freshness_context(db, dept(db, "VEG").id, "baseline", 3).data_changed_at is None


@pytest.mark.db
def test_freshness_context_counts_products_import_for_all_departments(db, product_factory):
    """商品マスタの取込(部門なし)は全部門の判定に効く(発注単位・持越可否の変更を反映する)。"""
    product_factory(code="VEG-001")
    db.add(ImportLog(kind="pos", department_id=dept(db, "VEG").id, file_name="a.csv", imported_count=1,
                     skipped_count=0, errors=[], finished_at=jst(2026, 10, 16, 9)))
    db.add(ImportLog(kind="products", department_id=None, file_name="p.csv", imported_count=1, skipped_count=0,
                     errors=[], finished_at=jst(2026, 10, 16, 11)))
    db.flush()
    for code in ("VEG", "FISH", "DELI"):
        assert freshness_context(db, dept(db, code).id, "baseline", 3).data_changed_at == jst(2026, 10, 16, 11)


@pytest.mark.db
def test_manual_inputs_use_statement_time(db, product_factory):
    """手入力の在庫・陳列残数の更新日時は文の実行時刻。now() だとトランザクションの開始時刻になり、
    その間に始まった計算の提案を最新と判定してしまう。"""
    from smdx_api.imports.manual import save_display_stock, save_manual_inventory

    veg, deli = dept(db, "VEG"), dept(db, "DELI")
    product_factory(code="VEG-001")
    product_factory(code="DELI-001", department="DELI")
    started = db.scalar(text("SELECT now()"))
    db.execute(text("SELECT pg_sleep(0.05)"))
    save_manual_inventory(db, veg, jst(2026, 10, 16, 8), [("VEG-001", 3)], None)
    save_display_stock(db, deli, date(2026, 10, 16), jst(2026, 10, 16, 12), [("DELI-001", 2)], None)
    for model in (InventorySnapshot, DisplayStockEntry):
        assert db.scalar(select(model.updated_at)) > started


@pytest.mark.db
def test_daily_sales_frame_sums_hourly_and_daily(db, product_factory, add_pos):
    p = product_factory(code="VEG-001")
    add_pos(p, date(2026, 10, 14), 5)
    add_pos(p, date(2026, 10, 15), 2, hour=10)
    add_pos(p, date(2026, 10, 15), 3, hour=11)
    add_pos(p, date(2026, 8, 1), 9)   # 期間外
    df = daily_sales_frame(db, [p.id], date(2026, 10, 1))
    assert list(df.columns) == ["product_code", "sales_date", "quantity"]
    assert sorted(zip(df.product_code, df.sales_date, df.quantity)) == [
        ("VEG-001", date(2026, 10, 14), 5), ("VEG-001", date(2026, 10, 15), 5)]
    assert hourly_sales_rows(db, [p.id], date(2026, 10, 1)) == {
        p.id: [(date(2026, 10, 15), 10, 2.0), (date(2026, 10, 15), 11, 3.0)]}
    hf = hourly_sales_frame(db, [p.id], date(2026, 10, 1))
    assert list(hf.columns) == ["product_code", "sales_date", "sales_hour", "quantity"] and len(hf) == 2


@pytest.mark.db
def test_daily_sales_frame_empty_has_columns(db, product_factory):
    p = product_factory()
    df = daily_sales_frame(db, [p.id], date(2026, 10, 1))
    assert df.empty and list(df.columns) == ["product_code", "sales_date", "quantity"]


@pytest.mark.db
def test_latest_pos_date_and_missing_days_per_department(db, product_factory, add_pos):
    v1, v2 = product_factory(code="VEG-001"), product_factory(code="VEG-002")
    f = product_factory(code="FISH-001", department="FISH")
    add_pos(v1, date(2026, 10, 12), 1)
    add_pos(v2, date(2026, 10, 14), 1, hour=12)
    add_pos(f, date(2026, 10, 15), 1)
    veg = dept(db, "VEG")
    assert latest_pos_date(db, veg.id) == date(2026, 10, 14)
    assert latest_pos_date(db, dept(db, "DELI").id) is None
    assert missing_pos_days(db, veg.id, date(2026, 10, 11), date(2026, 10, 15)) == {
        date(2026, 10, 11), date(2026, 10, 13), date(2026, 10, 15)}


@pytest.mark.db
def test_calendar_and_promotions(db, product_factory):
    p, q = product_factory(code="VEG-001"), product_factory(code="VEG-002")
    db.add_all([
        CalendarDay(date=date(2026, 11, 3), kind="holiday", name="文化の日"),
        CalendarDay(date=date(2026, 10, 18), kind="event", name="感謝祭"),
        CalendarDay(date=date(2027, 1, 1), kind="holiday", name="元日"),   # 期間外
        Promotion(product_id=p.id, start_date=date(2026, 10, 10), end_date=date(2026, 10, 16), description="a"),
        Promotion(product_id=p.id, start_date=date(2026, 9, 1), end_date=date(2026, 9, 5), description="期間外"),
        Promotion(product_id=q.id, start_date=date(2026, 10, 17), end_date=date(2026, 10, 20), description="b"),
    ])
    db.flush()
    cal = calendar_data(db, date(2026, 10, 1), date(2026, 11, 30))
    assert dict(cal.holidays) == {date(2026, 11, 3): "文化の日"} and dict(cal.events) == {date(2026, 10, 18): "感謝祭"}
    pf = promotions_frame(db, [p.id, q.id], date(2026, 10, 16), date(2026, 10, 17))
    assert list(pf.columns) == ["product_code", "start_date", "end_date"]
    assert sorted(pf.product_code) == ["VEG-001", "VEG-002"]


def test_weather_frame():
    assert weather_frame(ForecastResult(False)) is None
    rows = hourly_rows(date(2026, 10, 16), date(2026, 10, 16), code=61, temperature=18.0)
    df = weather_frame(ForecastResult(True, jst(2026, 10, 16, 9), rows))
    assert list(df.columns) == ["time", "weather_code", "temperature", "precipitation_probability", "precipitation"]
    assert len(df) == 24 and df["time"].iloc[0] == jst(2026, 10, 16, 0) and df["weather_code"].iloc[0] == 61


@pytest.mark.db
def test_backlog_batched_for_products_and_inventory_boundaries(db, product_factory, proposal_factory):
    # まとめて読んだ確定分を、商品ごとの在庫基準日時で絞る。納品時刻ちょうどの在庫は納品後とみなす(PR #7 レビューの指摘8)
    a, b = product_factory(code="VEG-001"), product_factory(code="VEG-002")
    proposal_factory(a, target=date(2026, 10, 16), qty=6, status="confirmed")   # 10/16 10:00 納品
    proposal_factory(a, target=date(2026, 10, 17), qty=4, status="confirmed")   # 10/17 10:00 納品
    proposal_factory(b, target=date(2026, 10, 16), qty=9, status="confirmed")
    orders = confirmed_orders(db, [a.id, b.id], date(2026, 10, 16), date(2026, 10, 18))
    assert sorted(orders[a.id]) == [(date(2026, 10, 16), 6), (date(2026, 10, 17), 4)]
    assert orders[b.id] == [(date(2026, 10, 16), 9)]
    # 在庫が納品時刻の前なら当日の納品分も発注残、ちょうど・後なら含めない
    assert backlog_qty(orders[a.id], jst(2026, 10, 16, 9, 59), date(2026, 10, 18), time(10)) == 10
    assert backlog_qty(orders[a.id], jst(2026, 10, 16, 10), date(2026, 10, 18), time(10)) == 4
    assert backlog_qty(orders[a.id], jst(2026, 10, 16, 10, 1), date(2026, 10, 18), time(10)) == 4
    # 対象の納品日以降は含めない
    assert backlog_qty(orders[a.id], jst(2026, 10, 16, 9), date(2026, 10, 17), time(10)) == 6
    assert backlog_qty(orders[b.id], jst(2026, 10, 16, 9), date(2026, 10, 18), time(10)) == 9
