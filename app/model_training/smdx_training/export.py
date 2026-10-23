"""モデルファイルの保存(詳細設計書「モデルファイル」の辞書)と版番号。

版番号は {granularity}-{学習終了日 YYYY.MM.DD}-{連番}(例: daily-2026.11.01-1。詳細設計書「モデルファイル」)。
保存の前に本体と同じ適合確認を通し、通らなければ既存のファイルを残したまま ModelIncompatible を送出する。
一時ファイルに書いてから置き換えるので、本体が書きかけのファイルを読むことはない。
"""
import os
from datetime import date
from pathlib import Path
from typing import Any

import joblib

from smdx_api.predictor.loader import check_model_object
from smdx_features.columns import Granularity, feature_columns


def next_version(granularity: Granularity, trained_to: date, out_dir: Path) -> str:
    base = f"{granularity}-{trained_to:%Y.%m.%d}"
    n = 1
    while (Path(out_dir) / f"report-{base}-{n}.md").exists():
        n += 1
    return f"{base}-{n}"


def export_model(
    pipeline: Any,
    granularity: Granularity,
    version: str,
    trained_from: date,
    trained_to: date,
    time_bands: list[int] | None,
    metrics: dict,
    path: Path,
) -> None:
    obj = {
        "model": pipeline,
        "meta": {
            "version": version,
            "granularity": granularity,
            "feature_columns": feature_columns(granularity),
            "trained_from": trained_from,
            "trained_to": trained_to,
            "time_bands": list(time_bands) if time_bands is not None else None,
            "metrics": dict(metrics),
        },
    }
    check_model_object(obj, granularity)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        joblib.dump(obj, tmp)
        # 保存したものを読み直しても適合することを確かめてから置き換える
        check_model_object(joblib.load(tmp), granularity)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
