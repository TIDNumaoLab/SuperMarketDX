"""評価: WAPE(主指標)・MAE、雨天日・祝日/行事日に絞った WAPE と日数、ベースラインとの比較。

ベースライン(sales_lag_7d、欠けていれば sales_avg_7d)より WAPE が悪いモデルは採用しない。
条件別の該当日数が7日未満なら参考扱いとする(詳細設計書 F-09 手順3〜5)。
"""
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from smdx_api.predictor.predict import baseline_values

RAIN_CODE_FROM = 51
MIN_CONDITION_DAYS = 7


def wape(actual, pred) -> float:
    actual, pred = np.asarray(actual, dtype=float), np.asarray(pred, dtype=float)
    total = actual.sum()
    return float(np.abs(actual - pred).sum() / total) if total > 0 else float("nan")


def mae(actual, pred) -> float:
    actual, pred = np.asarray(actual, dtype=float), np.asarray(pred, dtype=float)
    return float(np.abs(actual - pred).mean()) if len(actual) else float("nan")


@dataclass(frozen=True)
class ConditionMetric:
    wape: float
    days: int
    reference_only: bool


@dataclass
class Evaluation:
    # 候補名 → {"wape", "mae", "rainy": ConditionMetric, "holiday_event": ConditionMetric}
    candidates: dict[str, dict]
    baseline: dict
    selected: str | None


def _condition(valid: pd.DataFrame, pred: np.ndarray, mask: np.ndarray) -> ConditionMetric:
    days = int(valid.loc[mask, "target_date"].nunique())
    w = wape(valid.loc[mask, "quantity"], pred[mask]) if days else float("nan")
    return ConditionMetric(w, days, days < MIN_CONDITION_DAYS)


def _metrics(valid: pd.DataFrame, pred) -> dict:
    pred = np.asarray(pred, dtype=float)
    rainy = valid["weather_code"].fillna(0).astype(int).to_numpy() >= RAIN_CODE_FROM
    holiday_event = ((valid["is_holiday"] == 1) | (valid["is_event_day"] == 1)).to_numpy()
    return {
        "wape": wape(valid["quantity"], pred),
        "mae": mae(valid["quantity"], pred),
        "rainy": _condition(valid, pred, rainy),
        "holiday_event": _condition(valid, pred, holiday_event),
    }


def evaluate(valid: pd.DataFrame, predictions: Mapping[str, np.ndarray]) -> Evaluation:
    baseline = _metrics(valid, baseline_values(valid)[0])
    candidates = {name: _metrics(valid, pred) for name, pred in predictions.items()}
    limit = baseline["wape"] if np.isfinite(baseline["wape"]) else float("inf")
    better = {n: m["wape"] for n, m in candidates.items() if np.isfinite(m["wape"]) and m["wape"] < limit}
    return Evaluation(candidates, baseline, min(better, key=better.get) if better else None)
