"""モデルファイルの保存と版番号(詳細設計書「モデルファイル」)、本体の適合確認を通すこと。"""
from datetime import date

import joblib
import pytest

from smdx_api.predictor.loader import ModelIncompatible, check_model_object
from smdx_training.dataset import build_training_table, load_folder, time_split
from smdx_training.export import export_model, next_version
from smdx_training.train import fit_candidates

METRICS = {"wape": 0.2, "mae": 1.0, "baseline_wape": 0.3}


def test_next_version_increments(tmp_path):
    assert next_version("daily", date(2026, 11, 1), tmp_path) == "daily-2026.11.01-1"
    (tmp_path / "report-daily-2026.11.01-1.md").write_text("x", encoding="utf-8")
    assert next_version("daily", date(2026, 11, 1), tmp_path) == "daily-2026.11.01-2"
    assert next_version("time_band", date(2026, 11, 1), tmp_path) == "time_band-2026.11.01-1"


def test_exported_model_passes_conformance(sample_dir, tmp_path):
    tr, _ = time_split(build_training_table(load_folder(sample_dir), "daily", ["VEG", "FISH"]))
    pipe = fit_candidates(tr, "daily")["lightgbm"]
    path = tmp_path / "daily.joblib"
    export_model(pipe, "daily", "daily-2026.10.15-1", tr.target_date.min(), tr.target_date.max(), None, METRICS, path)
    loaded = check_model_object(joblib.load(path), "daily")
    assert loaded.version == "daily-2026.10.15-1" and loaded.metrics == METRICS
    assert loaded.trained_to == tr.target_date.max()


def test_export_refuses_incompatible_and_keeps_old_file(tmp_path):
    path = tmp_path / "daily.joblib"
    path.write_bytes(b"old")

    class Bad:
        def predict(self, X):
            raise ValueError("x")

    with pytest.raises(ModelIncompatible):
        export_model(Bad(), "daily", "daily-2026.10.15-1", date(2026, 1, 1), date(2026, 10, 1), None, METRICS, path)
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.tmp"))
