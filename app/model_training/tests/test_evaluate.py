"""評価(WAPE・MAE、条件別、ベースライン比較。詳細設計書 F-09 手順3〜5)。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from smdx_features.columns import sample_frame
from smdx_training.evaluate import ConditionMetric, evaluate, mae, wape


def valid_fixture(days: int = 28, rainy_days: int = 10, holiday_days: int = 8) -> pd.DataFrame:
    """sales_lag_7d が実績と一致する検証用の表(ベースラインの WAPE は 0)。1日1行。"""
    df = sample_frame("daily", rows=days)
    start = date(2026, 9, 18)
    df["target_date"] = [start + timedelta(days=i) for i in range(days)]
    df["quantity"] = np.arange(days, dtype=float) + 5
    df["sales_lag_7d"] = df["quantity"]
    df["weather_code"] = pd.array([61 if i < rainy_days else 1 for i in range(days)], dtype="Int64")
    df["is_holiday"] = [1 if i < holiday_days else 0 for i in range(days)]
    df["is_event_day"] = 0
    return df


def test_wape_and_mae():
    assert wape(np.array([10, 0, 10]), np.array([8, 1, 13])) == pytest.approx(6 / 20)
    assert mae(np.array([10, 0]), np.array([8, 1])) == pytest.approx(1.5)
    assert np.isnan(wape(np.array([0, 0]), np.array([1, 1])))


def test_evaluate_rejects_models_worse_than_baseline():
    valid = valid_fixture()
    ev = evaluate(valid, {"random_forest": valid.quantity.to_numpy() + 1.0})
    assert ev.baseline["wape"] == 0 and ev.selected is None


def test_evaluate_selects_best_model_beating_baseline():
    valid = valid_fixture()
    valid["sales_lag_7d"] = valid["quantity"] + 4  # ベースラインが外れる
    exact = valid.quantity.to_numpy()
    ev = evaluate(valid, {"random_forest": exact + 2.0, "lightgbm": exact + 1.0})
    assert ev.selected == "lightgbm"
    assert ev.candidates["lightgbm"]["wape"] < ev.candidates["random_forest"]["wape"] < ev.baseline["wape"]
    assert ev.candidates["lightgbm"]["mae"] == pytest.approx(1.0)


def test_condition_metrics_and_reference_flag():
    valid = valid_fixture(rainy_days=10, holiday_days=3)
    ev = evaluate(valid, {"lightgbm": valid.quantity.to_numpy() + 1.0})
    rainy, hol = ev.candidates["lightgbm"]["rainy"], ev.candidates["lightgbm"]["holiday_event"]
    assert isinstance(rainy, ConditionMetric)
    assert (rainy.days, rainy.reference_only) == (10, False)
    assert (hol.days, hol.reference_only) == (3, True)   # 7日未満は参考扱い
    assert ev.baseline["rainy"].days == 10


def test_condition_with_no_days_is_nan():
    valid = valid_fixture(rainy_days=0)
    ev = evaluate(valid, {"lightgbm": valid.quantity.to_numpy()})
    assert ev.candidates["lightgbm"]["rainy"].days == 0 and np.isnan(ev.candidates["lightgbm"]["rainy"].wape)
