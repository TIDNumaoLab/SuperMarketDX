"""予測とベースラインへの切替(詳細設計書「予測モデルのインターフェース定義」)。"""
import numpy as np

from smdx_api.predictor.predict import BASELINE_VERSION, TIME_BANDS_CHANGED, baseline_values, predict
from smdx_features.columns import sample_frame
from tests.predictor.conftest import ConstModel, SometimesNaNModel, SpyModel, model_dict


def feats(lag, avg, granularity="daily"):
    df = sample_frame(granularity, rows=len(lag))
    df["sales_lag_7d"] = np.array(lag, dtype=float)
    df["sales_avg_7d"] = np.array(avg, dtype=float)
    return df


def test_baseline_values():
    # 前週同曜日、欠けていれば直近7日平均、両方無ければ0と「実績なし」
    assert baseline_values(feats([3.0, np.nan, np.nan], [9.0, 4.0, np.nan])) == ([3.0, 4.0, 0.0], [False, False, True])


def test_predict_uses_model_and_zero_for_no_history(registry_with):
    reg = registry_with(model_dict())
    b = predict(reg, "daily", feats([3.0, np.nan], [9.0, np.nan]), weather_available=True, current_time_bands=None)
    assert b.values == [5.0, 0.0] and b.no_history == [False, True]
    assert (b.model_version, b.is_baseline, b.notice) == ("daily-2026.11.01-1", False, None)


def test_model_gets_only_feature_columns(registry_with):
    reg = registry_with(model_dict(model=SpyModel(1.0)))
    f = feats([3.0], [3.0])
    f["target_date"] = None  # 付随列は推論器に渡さない
    predict(reg, "daily", f, weather_available=True, current_time_bands=None)
    assert SpyModel.last_columns and "target_date" not in SpyModel.last_columns


def test_negative_output_clipped(registry_with):
    reg = registry_with(model_dict(model=ConstModel(-2.0)))
    assert predict(reg, "daily", feats([3.0], [3.0]), weather_available=True, current_time_bands=None).values == [0.0]


def test_baseline_when_no_model(tmp_path):
    from smdx_api.predictor.registry import ModelRegistry

    reg = ModelRegistry({"daily": tmp_path / "none", "time_band": tmp_path / "none2"})
    b = predict(reg, "daily", feats([3.0], [9.0]), weather_available=True, current_time_bands=None)
    assert (b.values, b.model_version, b.is_baseline, b.notice) == ([3.0], BASELINE_VERSION, True, None)


def test_baseline_when_weather_missing(registry_with):
    b = predict(registry_with(model_dict()), "daily", feats([3.0], [9.0]), weather_available=False, current_time_bands=None)
    assert (b.values, b.model_version, b.is_baseline) == ([3.0], "baseline", True)


def test_baseline_when_time_bands_changed(registry_with):
    reg = registry_with(model_dict("time_band"), granularity="time_band")
    b = predict(reg, "time_band", feats([2.0], [2.0], "time_band"), weather_available=True, current_time_bands=[10, 12, 16])
    assert b.is_baseline and b.values == [2.0] and b.notice == TIME_BANDS_CHANGED == "時間帯の設定が変わったため再学習が必要です"


def test_same_time_bands_uses_model(registry_with):
    reg = registry_with(model_dict("time_band"), granularity="time_band")
    b = predict(reg, "time_band", feats([2.0], [2.0], "time_band"), weather_available=True, current_time_bands=[10, 11, 14, 17])
    assert not b.is_baseline and b.values == [5.0]


def test_runtime_nan_falls_back_to_baseline(registry_with):
    reg = registry_with(model_dict(model=SometimesNaNModel(5.0)))
    b = predict(reg, "daily", feats([3.0, 4.0], [3.0, 4.0]), weather_available=True, current_time_bands=None)
    assert (b.values, b.is_baseline) == ([3.0, 4.0], True)


def test_rows_without_weather_use_baseline_row_by_row(registry_with):
    # 予報が一部の日にしか無い場合: 気象の欠けた行は中央値で埋めて推論せず、その行だけベースラインにする
    import pandas as pd

    f = feats([3.0, 4.0, 6.0], [3.0, 4.0, 6.0])
    f["weather_code"] = pd.array([1, None, 3], dtype="Int64")
    f.loc[2, "temperature"] = np.nan
    b = predict(registry_with(model_dict()), "daily", f, weather_available=True, current_time_bands=None)
    assert b.values == [5.0, 4.0, 6.0]
    assert b.row_is_baseline == [False, True, True]
    assert (b.is_baseline, b.model_version) == (False, "daily-2026.11.01-1")


def test_all_rows_without_weather_is_baseline(registry_with):
    import pandas as pd

    f = feats([3.0], [3.0])
    f["weather_code"] = pd.array([None], dtype="Int64")
    b = predict(registry_with(model_dict()), "daily", f, weather_available=True, current_time_bands=None)
    assert (b.values, b.row_is_baseline, b.is_baseline, b.model_version) == ([3.0], [True], True, "baseline")


def test_row_is_baseline_for_whole_batch_fallbacks(registry_with, tmp_path):
    b = predict(registry_with(model_dict()), "daily", feats([3.0, 4.0], [3.0, 4.0]), weather_available=False, current_time_bands=None)
    assert b.row_is_baseline == [True, True]
    ok = predict(registry_with(model_dict()), "daily", feats([3.0, 4.0], [3.0, 4.0]), weather_available=True, current_time_bands=None)
    assert ok.row_is_baseline == [False, False]
