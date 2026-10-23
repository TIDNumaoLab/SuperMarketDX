import pytest

from smdx_features.columns import (
    CATEGORICAL_COLUMNS,
    DAILY_FEATURE_COLUMNS,
    PRECIPITATION_SOURCE,
    TIME_BAND_FEATURE_COLUMNS,
    feature_columns,
    sample_frame,
)


def test_daily_columns_follow_design_order():
    assert DAILY_FEATURE_COLUMNS == [
        "product_code", "day_of_week", "is_holiday", "is_event_day", "holiday_seq", "is_promotion",
        "weather_code", "temperature", "precipitation", "sales_lag_7d", "sales_avg_7d",
    ]


def test_time_band_columns_insert_after_day_of_week():
    assert TIME_BAND_FEATURE_COLUMNS[:3] == ["product_code", "day_of_week", "time_band"]
    assert [c for c in TIME_BAND_FEATURE_COLUMNS if c != "time_band"] == DAILY_FEATURE_COLUMNS


def test_feature_columns_by_granularity():
    assert feature_columns("daily") == DAILY_FEATURE_COLUMNS
    assert feature_columns("time_band") == TIME_BAND_FEATURE_COLUMNS
    with pytest.raises(ValueError):
        feature_columns("weekly")


def test_categorical_and_precipitation_source():
    assert CATEGORICAL_COLUMNS == ["product_code", "day_of_week", "time_band", "weather_code"]
    # 学習用の過去実績(archive)は降水確率を返さないため、当面は降水量を使う(詳細設計書「特徴量」)
    assert PRECIPITATION_SOURCE == "amount"


@pytest.mark.parametrize("granularity", ["daily", "time_band"])
def test_sample_frame_has_exact_columns_and_types(granularity):
    df = sample_frame(granularity, rows=5)
    assert list(df.columns) == feature_columns(granularity) and len(df) == 5
    assert df["product_code"].map(type).eq(str).all()
    assert df["sales_lag_7d"].dtype.kind == "f" and df["is_holiday"].dtype.kind == "i"
    assert str(df["weather_code"].dtype) == "Int64"
