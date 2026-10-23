"""特徴量の列名・型(詳細設計書「特徴量」「予測モデルのインターフェース定義」の入力列)。"""
from typing import Literal

import numpy as np
import pandas as pd

Granularity = Literal["daily", "time_band"]

DAILY_FEATURE_COLUMNS = [
    "product_code",
    "day_of_week",
    "is_holiday",
    "is_event_day",
    "holiday_seq",
    "is_promotion",
    "weather_code",
    "temperature",
    "precipitation",
    "sales_lag_7d",
    "sales_avg_7d",
]
# 時間帯別は day_of_week の直後に time_band を持つ
TIME_BAND_FEATURE_COLUMNS = DAILY_FEATURE_COLUMNS[:2] + ["time_band"] + DAILY_FEATURE_COLUMNS[2:]

CATEGORICAL_COLUMNS = ["product_code", "day_of_week", "time_band", "weather_code"]

# precipitation 列の中身。学習用の過去実績(Open-Meteo archive)は降水確率を返さないため、当面は降水量(mm)を使う。
# 【確認事項】過去の降水確率が得られると分かったら "probability" に切り替えて再学習する(詳細設計書「特徴量」の precipitation の値)
PrecipitationSource = Literal["amount", "probability"]
PRECIPITATION_SOURCE: PrecipitationSource = "amount"

# 列の型。整数のカテゴリ・フラグは int64、天候コードは欠損(予報なし)がありうるため Int64、数値は float64(欠損は NaN)
DTYPES: dict[str, str] = {
    "product_code": "object",
    "day_of_week": "int64",
    "time_band": "int64",
    "is_holiday": "int64",
    "is_event_day": "int64",
    "holiday_seq": "int64",
    "is_promotion": "int64",
    "weather_code": "Int64",
    "temperature": "float64",
    "precipitation": "float64",
    "sales_lag_7d": "float64",
    "sales_avg_7d": "float64",
}


def feature_columns(granularity: Granularity) -> list[str]:
    if granularity == "daily":
        return list(DAILY_FEATURE_COLUMNS)
    if granularity == "time_band":
        return list(TIME_BAND_FEATURE_COLUMNS)
    raise ValueError(f"granularity は daily か time_band: {granularity}")


def coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    """特徴量の列を DTYPES の型にそろえる(付随列はそのまま)。"""
    out = df.copy()
    for col, dtype in DTYPES.items():
        if col in out.columns:
            out[col] = out[col].astype(dtype)
    return out


def sample_frame(granularity: Granularity, rows: int = 3) -> pd.DataFrame:
    """適合確認の試験入力。全列を持ち、型は本番と同じ。"""
    i = np.arange(rows)
    data = {
        "product_code": [f"SAMPLE-{n % 3 + 1}" for n in i],
        "day_of_week": i % 7,
        "time_band": np.array([10, 11, 14, 17])[i % 4],
        "is_holiday": i % 2,
        "is_event_day": (i + 1) % 2,
        "holiday_seq": i % 3,
        "is_promotion": i % 2,
        "weather_code": np.array([1, 61, 3])[i % 3],
        "temperature": 15.0 + i,
        "precipitation": (i % 2) * 1.5,
        "sales_lag_7d": 10.0 + i,
        "sales_avg_7d": 9.5 + i,
    }
    return coerce_types(pd.DataFrame({c: data[c] for c in feature_columns(granularity)}))
