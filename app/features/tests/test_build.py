from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from smdx_features.build import BandTarget, CalendarData, DailyTarget, build_daily_features, build_time_band_features
from smdx_features.columns import DAILY_FEATURE_COLUMNS, TIME_BAND_FEATURE_COLUMNS

JST = ZoneInfo("Asia/Tokyo")
NO_PROMO = pd.DataFrame(columns=["product_code", "start_date", "end_date"])


def hourly_fixture(day: date, rain_hours=(), temps=None) -> pd.DataFrame:
    rows = []
    for h in range(24):
        code = 61 if h in rain_hours else 1
        temp = (temps or {}).get(h, 15.0 + (h == 14) * 5)
        rows.append((datetime(day.year, day.month, day.day, h, tzinfo=JST), code, temp, 80.0 if code == 61 else 10.0,
                     2.0 if code == 61 else 0.0))
    return pd.DataFrame(rows, columns=["time", "weather_code", "temperature", "precipitation_probability", "precipitation"])


def daily_sales(rows):
    return pd.DataFrame(rows, columns=["product_code", "sales_date", "quantity"])


def test_build_daily_features_row():
    df = build_daily_features(
        [DailyTarget("VEG-001", date(2026, 10, 17), plan_date=date(2026, 10, 16))],
        daily_sales=daily_sales([("VEG-001", date(2026, 10, 10), 7), ("VEG-001", date(2026, 10, 15), 3)]),
        calendar=CalendarData({}, {}),
        promotions=pd.DataFrame({"product_code": ["VEG-001"], "start_date": [date(2026, 10, 17)], "end_date": [date(2026, 10, 18)]}),
        weather=hourly_fixture(date(2026, 10, 17), rain_hours={12, 13}),
        business_hours=(10, 20),
    )
    row = df.iloc[0]
    assert list(df.columns[: len(DAILY_FEATURE_COLUMNS)]) == DAILY_FEATURE_COLUMNS
    assert (row.product_code, row.day_of_week, row.is_promotion, row.sales_lag_7d) == ("VEG-001", 5, 1, 7)
    assert row.sales_avg_7d == pytest.approx(10 / 6)  # 10/10〜10/15 の6日(10/09 は最初の販売日より前)
    assert (row.weather_code, row.temperature, row.precipitation) == (61, 20.0, 2.0)  # 降水量(詳細設計書「特徴量」)
    assert (row.is_holiday, row.is_event_day, row.holiday_seq) == (0, 0, 0)   # 10/17 は普通の土曜(2日の休み)
    assert row.target_date == date(2026, 10, 17) and row.holiday_name is None


def test_long_weekend_and_names():
    cal = CalendarData({date(2026, 10, 12): "スポーツの日"}, {date(2026, 10, 12): "秋祭り"})
    df = build_daily_features([DailyTarget("VEG-001", date(2026, 10, 12), date(2026, 10, 11))], daily_sales([]), cal,
                              NO_PROMO, None, (10, 20))
    row = df.iloc[0]
    assert (row.is_holiday, row.is_event_day, row.holiday_seq, row.holiday_name) == (1, 1, 3, "スポーツの日")


def test_build_without_weather_gives_missing_and_no_history_gives_nan():
    df = build_daily_features([DailyTarget("VEG-001", date(2026, 10, 17), date(2026, 10, 16))], daily_sales([]),
                              CalendarData({}, {}), NO_PROMO, None, (10, 20))
    row = df.iloc[0]
    assert pd.isna(row.temperature) and pd.isna(row.weather_code) and pd.isna(row.precipitation)
    assert pd.isna(row.sales_lag_7d) and pd.isna(row.sales_avg_7d)
    assert str(df["weather_code"].dtype) == "Int64"


def test_rows_keep_target_order():
    targets = [DailyTarget("B", date(2026, 10, 17), date(2026, 10, 16)), DailyTarget("A", date(2026, 10, 16), date(2026, 10, 16))]
    df = build_daily_features(targets, daily_sales([]), CalendarData({}, {}), NO_PROMO, None, (10, 20))
    assert list(df.product_code) == ["B", "A"]


def test_build_time_band_sums_hours_in_band():
    # 前週同曜日(10/09)の 11〜13時の販売 2+3+4=9、17〜19時の販売 5+6+7=18。10時帯は売れたことが無い
    hourly = pd.DataFrame(
        [("DELI-001", date(2026, 10, 9), h, q) for h, q in [(11, 2), (12, 3), (13, 4), (17, 5), (18, 6), (19, 7)]],
        columns=["product_code", "sales_date", "sales_hour", "quantity"],
    )
    targets = [BandTarget("DELI-001", date(2026, 10, 16), b, plan_date=date(2026, 10, 15)) for b in (10, 11, 14, 17)]
    df = build_time_band_features(targets, hourly, CalendarData({}, {}), NO_PROMO,
                                  hourly_fixture(date(2026, 10, 16), rain_hours={15}, temps={11: 18.0, 12: 20.0, 13: 22.0}),
                                  time_bands=[10, 11, 14, 17], close_hour=20)
    assert list(df.columns[: len(TIME_BAND_FEATURE_COLUMNS)]) == TIME_BAND_FEATURE_COLUMNS
    by_band = df.set_index("time_band")
    assert pd.isna(by_band.loc[10, "sales_lag_7d"])
    assert by_band.loc[11, "sales_lag_7d"] == 9 and by_band.loc[17, "sales_lag_7d"] == 18
    assert pd.isna(by_band.loc[14, "sales_lag_7d"])  # 14時帯も売れたことが無い → 実績なし
    assert by_band.loc[11, "temperature"] == pytest.approx(20.0)
    assert by_band.loc[14, "weather_code"] == 61 and by_band.loc[11, "weather_code"] == 1


def _ten_a_day(until_day: int):
    # 10/01〜10/{until_day} まで毎日10個売れた
    return daily_sales([("VEG-001", date(2026, 10, d), 10) for d in range(1, until_day + 1)])


def test_unimported_pos_day_is_not_counted_as_zero():
    # 計画日 10/16 → 基準日 10/15。POS は 10/14 までしか取り込まれていない(前日分が未更新)
    t = [DailyTarget("VEG-001", date(2026, 10, 17), date(2026, 10, 16))]
    stale = build_daily_features(t, _ten_a_day(14), CalendarData(), NO_PROMO, None, (10, 20), known_through=date(2026, 10, 14))
    assert stale.iloc[0].sales_avg_7d == pytest.approx(10.0)   # 10/08〜10/14 だけで平均する
    # known_through を渡さないと、10/15 を「売上0」とみなしてしまう(従来の動き)
    naive = build_daily_features(t, _ten_a_day(14), CalendarData(), NO_PROMO, None, (10, 20))
    assert naive.iloc[0].sales_avg_7d == pytest.approx(60 / 7)


def test_lag_steps_back_past_unimported_days():
    # 対象日 10/22 の前週同曜日は 10/15 だが未取込 → 10/08 の実績を使う
    t = [DailyTarget("VEG-001", date(2026, 10, 22), date(2026, 10, 16))]
    df = build_daily_features(t, _ten_a_day(14), CalendarData(), NO_PROMO, None, (10, 20), known_through=date(2026, 10, 14))
    assert df.iloc[0].sales_lag_7d == 10


def test_time_band_respects_known_through():
    hourly = pd.DataFrame([("DELI-001", date(2026, 10, d), 12, 3) for d in range(1, 15)],
                          columns=["product_code", "sales_date", "sales_hour", "quantity"])
    t = [BandTarget("DELI-001", date(2026, 10, 17), 11, date(2026, 10, 16))]
    df = build_time_band_features(t, hourly, CalendarData(), NO_PROMO, None, [10, 11, 14, 17], 20,
                                  known_through=date(2026, 10, 14))
    assert df.iloc[0].sales_avg_7d == pytest.approx(3.0)


def test_missing_days_are_not_counted_as_zero():
    # 10/10 は POS が1行も無い(未取込日)。7日平均からも前週同曜日からも外す
    sales = daily_sales([("VEG-001", date(2026, 10, d), 10) for d in range(1, 16) if d != 10])
    t = [DailyTarget("VEG-001", date(2026, 10, 17), date(2026, 10, 16))]
    df = build_daily_features(t, sales, CalendarData(), NO_PROMO, None, (10, 20), missing_days={date(2026, 10, 10)})
    assert df.iloc[0].sales_avg_7d == pytest.approx(10.0)
    lag = build_daily_features([DailyTarget("VEG-001", date(2026, 10, 17), date(2026, 10, 9))], sales, CalendarData(),
                               NO_PROMO, None, (10, 20), missing_days={date(2026, 10, 3)})
    assert pd.isna(lag.iloc[0].sales_lag_7d)   # 基準日 10/08 以前の同じ曜日 10/03 が未取込


def test_time_band_missing_days():
    hourly = pd.DataFrame([("DELI-001", date(2026, 10, d), 12, 3) for d in range(1, 16) if d != 12],
                          columns=["product_code", "sales_date", "sales_hour", "quantity"])
    t = [BandTarget("DELI-001", date(2026, 10, 17), 11, date(2026, 10, 16))]
    df = build_time_band_features(t, hourly, CalendarData(), NO_PROMO, None, [10, 11, 14, 17], 20,
                                  missing_days={date(2026, 10, 12)})
    assert df.iloc[0].sales_avg_7d == pytest.approx(3.0)
