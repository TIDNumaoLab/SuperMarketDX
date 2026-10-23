"""予測の試験の共通部品。"""
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pytest

from smdx_api.predictor.registry import ModelRegistry
from smdx_features.columns import feature_columns


class ConstModel:
    """常に同じ値を返す推論器。"""

    def __init__(self, v: float) -> None:
        self.v = v

    def predict(self, X):
        return np.full(len(X), self.v, dtype=float)


class SpyModel(ConstModel):
    """推論器に渡された列を記録する(joblib で保存するためモジュールの直下に置く)。"""

    last_columns: list[str] = []

    def predict(self, X):
        SpyModel.last_columns = list(X.columns)
        return super().predict(X)


class SometimesNaNModel(ConstModel):
    """適合確認(3行)は通り、運用時(2行)だけ NaN を返す。"""

    def predict(self, X):
        out = super().predict(X)
        if len(X) == 2:
            out[1] = np.nan
        return out


def model_dict(granularity: str = "daily", **over) -> dict:
    meta = {
        "version": f"{granularity}-2026.11.01-1",
        "granularity": granularity,
        "feature_columns": feature_columns(granularity),
        "trained_from": date(2025, 9, 1),
        "trained_to": date(2026, 10, 31),
        "time_bands": None if granularity == "daily" else [10, 11, 14, 17],
        "metrics": {"wape": 0.2, "mae": 1.0, "baseline_wape": 0.3},
    }
    meta.update(over.pop("meta", {}))
    d = {"model": ConstModel(5.0), "meta": meta}
    d.update(over)
    return d


@pytest.fixture
def registry_with(tmp_path: Path):
    """obj を保存したモデルファイルを読む ModelRegistry を作る。"""

    def make(obj, granularity: str = "daily") -> ModelRegistry:
        p = tmp_path / f"{granularity}.joblib"
        joblib.dump(obj, p)
        other = "time_band" if granularity == "daily" else "daily"
        return ModelRegistry({granularity: p, other: tmp_path / "missing.joblib"})

    return make
