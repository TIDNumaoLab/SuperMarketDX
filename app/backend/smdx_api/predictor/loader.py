"""モデルファイル(joblib で保存した辞書)の読み込みと適合確認。

辞書のキー: model(predict(DataFrame) -> 1次元配列 を持つ推論器)と meta
(version、granularity、feature_columns、trained_from、trained_to、time_bands、metrics)。
適合確認はモデル作成用プロジェクトでもモデルを渡す前に通す(同じ関数を使う)。
"""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np

from smdx_features.columns import feature_columns, sample_frame

Granularity = Literal["daily", "time_band"]
REQUIRED_META = ("version", "granularity", "feature_columns", "trained_from", "trained_to", "time_bands", "metrics")


class ModelIncompatible(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoadedModel:
    model: Any
    version: str
    granularity: Granularity
    feature_columns: list[str]
    time_bands: list[int] | None
    trained_from: date
    trained_to: date
    metrics: dict


def check_model_object(obj: Any, granularity: Granularity) -> LoadedModel:
    if not isinstance(obj, dict) or "model" not in obj:
        raise ModelIncompatible("必須キーがありません: model")
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        raise ModelIncompatible("必須キーがありません: meta")
    for key in REQUIRED_META:
        if key not in meta:
            raise ModelIncompatible(f"必須キーがありません: meta.{key}")
    if meta["granularity"] != granularity:
        raise ModelIncompatible("granularity が部門と合いません")
    expected = feature_columns(granularity)
    if list(meta["feature_columns"]) != expected:
        raise ModelIncompatible("feature_columns が本体の特徴量と一致しません")

    sample = sample_frame(granularity)
    try:
        out = np.asarray(obj["model"].predict(sample[expected]), dtype=float).ravel()
    except Exception:
        raise ModelIncompatible("試験入力での推論に失敗しました") from None
    if len(out) != len(sample):
        raise ModelIncompatible("出力の行数が入力と一致しません")
    if not np.isfinite(out).all():
        raise ModelIncompatible("出力に数値でない値が含まれます")

    return LoadedModel(
        model=obj["model"],
        version=str(meta["version"]),
        granularity=granularity,
        feature_columns=expected,
        time_bands=list(meta["time_bands"]) if meta["time_bands"] is not None else None,
        trained_from=meta["trained_from"],
        trained_to=meta["trained_to"],
        metrics=dict(meta["metrics"]),
    )


def load_model_file(path: Path, granularity: Granularity) -> LoadedModel:
    path = Path(path)
    if not path.exists():
        raise ModelIncompatible("モデルファイルがありません")
    try:
        obj = joblib.load(path)
    except Exception:
        raise ModelIncompatible("モデルファイルを読み込めません") from None
    return check_model_object(obj, granularity)
