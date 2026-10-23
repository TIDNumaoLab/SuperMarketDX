"""特徴量の表の組み立て(日別・時間帯別)。

入力の表:
- daily_sales: product_code, sales_date, quantity(日計と時刻つきを合計済みでも、別々の行でもよい。日ごとに合計する)
- hourly_sales: product_code, sales_date, sales_hour, quantity(時刻つきの行のみ)
- promotions: product_code, start_date, end_date
- weather: 1時間ごとの気象(time, weather_code, temperature, precipitation_probability, precipitation)。None は全行欠損
出力: feature_columns(granularity) の列 + 付随列 target_date・holiday_name(行の順は targets の順)。
付随列は推論器に渡さない。
known_through: POS が取り込まれている最新日。基準日より前なら、基準日の代わりにこの日までで実績系の特徴量を作る
(前日分の POS が未取込の日を「売上0」とみなさない。詳細設計書「欠損時の扱い」の「前日分のPOSが無い」)。
missing_days: 基準日より前で POS が1行も無い日(未取込日)。実績系の特徴量で「売上0」ではなく「実績なし」として扱う。
"""
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd

from smdx_features.calendar import calendar_flags
from smdx_features.columns import PRECIPITATION_SOURCE, PrecipitationSource, coerce_types, feature_columns
from smdx_features.sales import SalesSeries, base_date, sales_avg_7d, sales_lag_7d
from smdx_features.weather import WeatherSummary, summarize

EXTRA_COLUMNS = ["target_date", "holiday_name"]


@dataclass(frozen=True)
class CalendarData:
    holidays: Mapping[date, str] = field(default_factory=dict)
    events: Mapping[date, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyTarget:
    product_code: str
    target_date: date
    plan_date: date


@dataclass(frozen=True)
class BandTarget:
    product_code: str
    target_date: date
    time_band: int
    plan_date: date


class _Promotions:
    def __init__(self, promotions: pd.DataFrame) -> None:
        self._ranges: dict[str, list[tuple[date, date]]] = defaultdict(list)
        for code, start, end in zip(promotions["product_code"], promotions["start_date"], promotions["end_date"]):
            self._ranges[code].append((pd.Timestamp(start).date(), pd.Timestamp(end).date()))

    def active(self, code: str, day: date) -> bool:
        return any(s <= day <= e for s, e in self._ranges.get(code, ()))


class _Weather:
    """同じ日・時間の範囲の集約を何度も計算しないよう、結果を覚えておく。"""

    def __init__(self, weather: pd.DataFrame | None, source: PrecipitationSource) -> None:
        self._source = source
        self._by_day: dict[date, pd.DataFrame] = {}
        if weather is not None and not weather.empty:
            times = pd.to_datetime(weather["time"])
            for d, g in weather.groupby(times.dt.date.to_numpy()):
                self._by_day[d] = g
        self._cache: dict[tuple, WeatherSummary] = {}

    def get(self, day: date, start: int, end: int, temperature: Literal["max", "mean"]) -> WeatherSummary:
        key = (day, start, end, temperature)
        if key not in self._cache:
            rows = self._by_day.get(day)
            self._cache[key] = (
                WeatherSummary(None, None, None) if rows is None else summarize(rows, day, start, end, temperature, self._source)
            )
        return self._cache[key]


def _series_by_product(daily_sales: pd.DataFrame, missing_days: Collection[date]) -> dict[str, SalesSeries]:
    rows: dict[str, list] = defaultdict(list)
    for code, d, q in zip(daily_sales["product_code"], daily_sales["sales_date"], daily_sales["quantity"]):
        rows[code].append((pd.Timestamp(d).date(), q))
    return {code: SalesSeries.from_rows(r, missing_days) for code, r in rows.items()}


def _band_of(hour: int, time_bands: Sequence[int], close_hour: int) -> int | None:
    """時刻が属する時間帯(開始時 ≤ 時 < 次の開始時、最後は閉店時まで)。どこにも属さなければ None。"""
    bands = sorted(time_bands)
    for i, b in enumerate(bands):
        end = bands[i + 1] if i + 1 < len(bands) else close_hour
        if b <= hour < end:
            return b
    return None


def _common_row(code: str, target: date, plan_date: date, series: SalesSeries | None, calendar: CalendarData,
                promos: _Promotions, w: WeatherSummary, known_through: date | None) -> dict:
    flags = calendar_flags(target, calendar.holidays, calendar.events)
    base = base_date(plan_date)
    if known_through is not None and known_through < base:
        base = known_through
    s = series or SalesSeries({})
    lag, avg = sales_lag_7d(s, target, base), sales_avg_7d(s, base)
    return {
        "product_code": code,
        "day_of_week": target.weekday(),
        "is_holiday": int(flags.is_holiday),
        "is_event_day": int(flags.is_event_day),
        "holiday_seq": flags.holiday_seq,
        "is_promotion": int(promos.active(code, target)),
        "weather_code": w.weather_code,
        "temperature": float("nan") if w.temperature is None else w.temperature,
        "precipitation": float("nan") if w.precipitation is None else w.precipitation,
        "sales_lag_7d": float("nan") if lag is None else lag,
        "sales_avg_7d": float("nan") if avg is None else avg,
        "target_date": target,
        "holiday_name": flags.holiday_name,
    }


def _frame(rows: list[dict], granularity: str) -> pd.DataFrame:
    cols = feature_columns(granularity) + EXTRA_COLUMNS
    df = pd.DataFrame(rows, columns=cols)
    df["weather_code"] = pd.array(df["weather_code"].tolist(), dtype="Int64")
    return coerce_types(df)


def build_daily_features(
    targets: Sequence[DailyTarget],
    daily_sales: pd.DataFrame,
    calendar: CalendarData,
    promotions: pd.DataFrame,
    weather: pd.DataFrame | None,
    business_hours: tuple[int, int],
    precipitation_source: PrecipitationSource = PRECIPITATION_SOURCE,
    known_through: date | None = None,
    missing_days: Collection[date] = (),
) -> pd.DataFrame:
    series = _series_by_product(daily_sales, missing_days)
    promos, wx = _Promotions(promotions), _Weather(weather, precipitation_source)
    open_h, close_h = business_hours
    rows = [
        _common_row(t.product_code, t.target_date, t.plan_date, series.get(t.product_code), calendar, promos,
                    wx.get(t.target_date, open_h, close_h, "max"), known_through)
        for t in targets
    ]
    return _frame(rows, "daily")


def build_time_band_features(
    targets: Sequence[BandTarget],
    hourly_sales: pd.DataFrame,
    calendar: CalendarData,
    promotions: pd.DataFrame,
    weather: pd.DataFrame | None,
    time_bands: Sequence[int],
    close_hour: int,
    precipitation_source: PrecipitationSource = PRECIPITATION_SOURCE,
    known_through: date | None = None,
    missing_days: Collection[date] = (),
) -> pd.DataFrame:
    # 商品×時間帯ごとの日別の販売数(時間帯に含まれる時の合計)
    band_rows: dict[tuple[str, int], list] = defaultdict(list)
    for code, d, h, q in zip(hourly_sales["product_code"], hourly_sales["sales_date"], hourly_sales["sales_hour"],
                             hourly_sales["quantity"]):
        band = _band_of(int(h), time_bands, close_hour)
        if band is not None:
            band_rows[(code, band)].append((pd.Timestamp(d).date(), q))
    series = {k: SalesSeries.from_rows(v, missing_days) for k, v in band_rows.items()}
    promos, wx = _Promotions(promotions), _Weather(weather, precipitation_source)
    bands = sorted(time_bands)
    rows = []
    for t in targets:
        i = bands.index(t.time_band)
        end = bands[i + 1] if i + 1 < len(bands) else close_hour
        row = _common_row(t.product_code, t.target_date, t.plan_date, series.get((t.product_code, t.time_band)),
                          calendar, promos, wx.get(t.target_date, t.time_band, end, "mean"), known_through)
        row["time_band"] = t.time_band
        rows.append(row)
    return _frame(rows, "time_band")
