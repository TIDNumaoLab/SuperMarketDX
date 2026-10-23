"""1時間ごとの気象(予報または実績)から、日別・時間帯別の特徴量への集約。

詳細設計書「日別の気象の集約」: 天候区分 = 降水を伴うコード(51以上)が1時間でもあればその中の最頻値、
無ければ全時間の最頻値。気温 = 日別は最高、時間帯別は平均。降水 = 範囲内の最大。
範囲は 開始時 ≤ 時 < 終了時。最頻値が同数のときは大きいコード(より悪い天候)を採る(詳細設計書「特徴量」の集約の範囲と同数の扱い)。
"""
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from smdx_features.columns import PRECIPITATION_SOURCE, PrecipitationSource

RAIN_CODE_FROM = 51
_PRECIP_COLUMN = {"amount": "precipitation", "probability": "precipitation_probability"}


@dataclass(frozen=True)
class WeatherSummary:
    weather_code: int | None
    temperature: float | None
    precipitation: float | None


def representative_code(codes: Sequence[int]) -> int | None:
    if not codes:
        return None
    rain = [c for c in codes if c >= RAIN_CODE_FROM]
    counts = Counter(rain or codes)
    return max(counts, key=lambda c: (counts[c], c))


def _none_if_nan(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def summarize(
    hourly: pd.DataFrame,
    day: date,
    start_hour: int,
    end_hour: int,
    temperature: Literal["max", "mean"],
    precipitation_source: PrecipitationSource = PRECIPITATION_SOURCE,
) -> WeatherSummary:
    """hourly の列: time(JST aware)、weather_code、temperature、precipitation_probability、precipitation。"""
    if hourly.empty:
        return WeatherSummary(None, None, None)
    times = pd.to_datetime(hourly["time"])
    mask = (times.dt.date == day) & (times.dt.hour >= start_hour) & (times.dt.hour < end_hour)
    rows = hourly[mask.to_numpy()]
    if rows.empty:
        return WeatherSummary(None, None, None)
    codes = [int(c) for c in rows["weather_code"].dropna()]
    temps = rows["temperature"].dropna()
    temp = None if temps.empty else float(temps.max() if temperature == "max" else temps.mean())
    precip = _none_if_nan(pd.to_numeric(rows[_PRECIP_COLUMN[precipitation_source]], errors="coerce").max())
    return WeatherSummary(representative_code(codes), temp, precip)
