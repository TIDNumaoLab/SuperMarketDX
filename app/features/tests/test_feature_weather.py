from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from smdx_features.weather import WeatherSummary, representative_code, summarize

JST = ZoneInfo("Asia/Tokyo")
D = date(2026, 10, 16)


def _hourly(day: date, values: dict[int, tuple]) -> pd.DataFrame:
    """values: {時: (天候コード, 気温, 降水確率, 降水量)}"""
    rows = [(datetime(day.year, day.month, day.day, h, tzinfo=JST), *v) for h, v in sorted(values.items())]
    return pd.DataFrame(rows, columns=["time", "weather_code", "temperature", "precipitation_probability", "precipitation"])


@pytest.mark.parametrize("codes,expected", [
    ([1, 1, 3], 1),
    ([1, 1, 61, 3], 61),          # 降水を伴うコード(51以上)が1時間でもあれば、その中の最頻値
    ([61, 80, 80, 61], 80),       # 同数なら大きいコード(詳細設計書「特徴量」)
    ([2, 3], 3),
    ([], None),
])
def test_representative_code(codes, expected):
    assert representative_code(codes) == expected


def test_daily_summary_uses_business_hours_only():
    h = _hourly(D, {9: (61, 30.0, 90, 9.0), 10: (1, 18.0, 10, 0.0), 14: (3, 22.0, 30, 0.0),
                    19: (61, 16.0, 80, 1.5), 20: (95, 10.0, 99, 20.0)})
    assert summarize(h, D, 10, 20, "max") == WeatherSummary(61, 22.0, 1.5)


def test_band_summary_mean_and_probability_source():
    h = _hourly(D, {11: (1, 18.0, 10, 0.0), 12: (3, 20.0, 40, 0.0), 13: (3, 22.0, 30, 0.0), 14: (61, 9.0, 99, 9.0)})
    assert summarize(h, D, 11, 14, "mean", precipitation_source="probability") == WeatherSummary(3, 20.0, 40.0)


def test_other_days_are_ignored():
    h = pd.concat([_hourly(D, {12: (1, 20.0, 10, 0.0)}), _hourly(date(2026, 10, 17), {12: (95, 35.0, 99, 50.0)})])
    assert summarize(h, D, 10, 20, "max") == WeatherSummary(1, 20.0, 0.0)


def test_partial_hours_do_not_fail():
    h = _hourly(D, {15: (3, 21.0, 20, 0.0)})
    assert summarize(h, D, 10, 20, "max") == WeatherSummary(3, 21.0, 0.0)


def test_no_hours_gives_missing():
    assert summarize(_hourly(D, {}), D, 10, 20, "max") == WeatherSummary(None, None, None)
    assert summarize(_hourly(D, {3: (1, 5.0, 0, 0.0)}), D, 10, 20, "max") == WeatherSummary(None, None, None)


def test_missing_precipitation_values_give_none():
    h = _hourly(D, {12: (1, 20.0, None, None)})
    assert summarize(h, D, 10, 20, "max", precipitation_source="probability") == WeatherSummary(1, 20.0, None)
