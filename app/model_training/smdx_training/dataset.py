"""学習用の表の作成。

入力はサンプル出力と同じ形式のフォルダ(products.csv・pos_sales.csv・weather.csv・calendar.csv・promotions.csv、
あれば true_demand.csv)。実データは同じ形式に書き出して使う(詳細設計書「学習・評価・バックテスト」)。
情報の時点の規則を学習データにも当てはめる: 生鮮の計画日 = 対象日 − リードタイム、惣菜の計画日 = 対象日 − 1(前日作成)。
基準日 = 計画日 − 1。前週同曜日・7日平均がそろわない最初の14日は除く。
POS が1行も無い日(店舗全体)は未取込日とみなし、学習・評価の対象日から外し、実績系の特徴量でも「実績なし」とする。
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from smdx_features.build import BandTarget, CalendarData, DailyTarget, build_daily_features, build_time_band_features
from smdx_features.columns import Granularity

DEFAULT_DEPARTMENTS: dict[str, list[str]] = {"daily": ["VEG", "FISH"], "time_band": ["DELI"]}
WARMUP_DAYS = 14
TZ = "Asia/Tokyo"


@dataclass
class RawData:
    products: pd.DataFrame     # product_code, product_name, department_code, order_unit, lead_time_days, can_carry_over, cost_price, selling_price
    pos: pd.DataFrame          # sales_date(date), sales_hour(Int64、日計は欠損), product_code, quantity
    weather: pd.DataFrame      # time(JST aware), weather_code, temperature, precipitation_probability, precipitation
    calendar: pd.DataFrame     # date(date), kind, name
    promotions: pd.DataFrame   # product_code, start_date(date), end_date(date)
    true_demand: pd.DataFrame | None  # date(date), time_band(Int64), product_code, demand


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _dates(s: pd.Series) -> pd.Series:
    return s.map(date.fromisoformat)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", None), errors="coerce")


def load_folder(folder: Path) -> RawData:
    folder = Path(folder)
    p = _read(folder / "products.csv")
    products = p.assign(
        order_unit=p.order_unit.astype(int),
        lead_time_days=p.lead_time_days.astype(int),
        can_carry_over=p.can_carry_over.eq("1"),
        cost_price=_num(p.get("cost_price", pd.Series([""] * len(p)))),
        selling_price=_num(p.get("selling_price", pd.Series([""] * len(p)))),
    )
    s = _read(folder / "pos_sales.csv")
    hours = s.sales_time.map(lambda t: int(t[:2]) if t else None)
    pos = pd.DataFrame({
        "sales_date": _dates(s.sales_date),
        "sales_hour": pd.array(hours.tolist(), dtype="Int64"),
        "product_code": s.product_code,
        "quantity": s.quantity.astype(int),
    })
    w = _read(folder / "weather.csv")
    weather = pd.DataFrame({
        "time": pd.to_datetime(w.observed_time, format="%Y-%m-%d %H:%M").dt.tz_localize(TZ),
        "weather_code": w.weather_code.astype(int),
        "temperature": w.temperature.astype(float),
        "precipitation_probability": _num(w.precipitation_probability),
        "precipitation": _num(w.precipitation),
    })
    c = _read(folder / "calendar.csv")
    calendar = pd.DataFrame({"date": _dates(c.date), "kind": c.kind, "name": c.name})
    pr = _read(folder / "promotions.csv")
    promotions = pd.DataFrame({"product_code": pr.product_code, "start_date": _dates(pr.start_date), "end_date": _dates(pr.end_date)})
    true_demand = None
    if (folder / "true_demand.csv").exists():
        t = _read(folder / "true_demand.csv")
        true_demand = pd.DataFrame({
            "date": _dates(t.date),
            "time_band": pd.array([int(v) if v else None for v in t.time_band], dtype="Int64"),
            "product_code": t.product_code,
            "demand": t.demand.astype(int),
        })
    return RawData(products, pos, weather, calendar, promotions, true_demand)


def _calendar(raw: RawData) -> CalendarData:
    cal = raw.calendar
    return CalendarData(
        holidays=dict(zip(cal[cal.kind == "holiday"].date, cal[cal.kind == "holiday"].name)),
        events=dict(zip(cal[cal.kind == "event"].date, cal[cal.kind == "event"].name)),
    )


def build_training_table(
    raw: RawData,
    granularity: Granularity,
    departments: Sequence[str],
    business_hours: tuple[int, int] = (10, 20),
    time_bands: Sequence[int] = (10, 11, 14, 17),
) -> pd.DataFrame:
    """特徴量の列 + target_date + 目的変数 quantity(販売数)。"""
    unknown = set(departments) - set(raw.products.department_code)
    if unknown:
        raise ValueError(f"未登録の部門です: {', '.join(sorted(unknown))}")
    products = raw.products[raw.products.department_code.isin(departments)]
    first, last = raw.pos.sales_date.min(), raw.pos.sales_date.max()
    imported = set(raw.pos.sales_date)
    missing = {first + timedelta(days=i) for i in range((last - first).days + 1)} - imported
    days = [d for i in range(WARMUP_DAYS, (last - first).days + 1) if (d := first + timedelta(days=i)) in imported]
    cal = _calendar(raw)

    if granularity == "daily":
        daily = raw.pos.groupby(["product_code", "sales_date"], as_index=False).quantity.sum()
        sold = {(c, d): q for c, d, q in zip(daily.product_code, daily.sales_date, daily.quantity)}
        targets = [DailyTarget(code, d, d - timedelta(days=int(lt)))
                   for code, lt in zip(products.product_code, products.lead_time_days) for d in days]
        table = build_daily_features(targets, daily, cal, raw.promotions, raw.weather, business_hours,
                                     missing_days=missing)
        table["quantity"] = [float(sold.get((t.product_code, t.target_date), 0)) for t in targets]
        return table

    hourly = raw.pos[raw.pos.sales_hour.notna()]
    bands = sorted(time_bands)
    ends = dict(zip(bands, bands[1:] + [business_hours[1]]))
    sold_band: dict[tuple, float] = {}
    for code, d, h, q in zip(hourly.product_code, hourly.sales_date, hourly.sales_hour, hourly.quantity):
        b = next((b for b in bands if b <= h < ends[b]), None)
        if b is not None:
            sold_band[(code, d, b)] = sold_band.get((code, d, b), 0.0) + q
    targets = [BandTarget(code, d, b, d - timedelta(days=1)) for code in products.product_code for d in days for b in bands]
    table = build_time_band_features(targets, hourly, cal, raw.promotions, raw.weather, bands, business_hours[1],
                                     missing_days=missing)
    table["quantity"] = [sold_band.get((t.product_code, t.target_date, t.time_band), 0.0) for t in targets]
    return table


def time_split(table: pd.DataFrame, valid_weeks: int = 4) -> tuple[pd.DataFrame, pd.DataFrame]:
    """target_date の最終日から遡る valid_weeks 週を検証期間にする。"""
    cutoff = table.target_date.max() - timedelta(weeks=valid_weeks)
    mask = table.target_date > cutoff
    return table[~mask].reset_index(drop=True), table[mask].reset_index(drop=True)
