"""候補アルゴリズムの学習(詳細設計書 F-09 手順2)。"""
import pickle

import numpy as np

from smdx_features.columns import DAILY_FEATURE_COLUMNS, TIME_BAND_FEATURE_COLUMNS
from smdx_training.dataset import build_training_table, load_folder, time_split
from smdx_training.train import fit_candidates, make_candidates


def test_candidates_are_rf_and_lightgbm_with_seed():
    c = make_candidates("daily", seed=7)
    assert set(c) == {"random_forest", "lightgbm"}
    assert c["random_forest"].named_steps["model"].random_state == 7
    assert c["lightgbm"].named_steps["model"].random_state == 7
    # n_jobs を指定しないと LightGBM が物理コア数を調べ、Windows では長いエラーを表示する(本体での推論時も)
    assert c["lightgbm"].named_steps["model"].n_jobs == -1


def test_fit_candidates_predicts(sample_dir):
    tr, va = time_split(build_training_table(load_folder(sample_dir), "daily", ["VEG", "FISH"]))
    models = fit_candidates(tr, "daily")
    for name, pipe in models.items():
        pred = pipe.predict(va[DAILY_FEATURE_COLUMNS])
        assert len(pred) == len(va) and np.isfinite(pred).all(), name


def test_time_band_model_fits(sample_dir):
    tr, va = time_split(build_training_table(load_folder(sample_dir), "time_band", ["DELI"]))
    pipe = fit_candidates(tr, "time_band")["lightgbm"]
    assert len(pipe.predict(va[TIME_BAND_FEATURE_COLUMNS])) == len(va)


def test_trained_pipeline_does_not_need_smdx_training(sample_dir):
    # 本体はモデル作成用プロジェクトを入れないため、保存したモデルが smdx_training の部品に依存してはいけない
    tr, _ = time_split(build_training_table(load_folder(sample_dir), "daily", ["VEG"]))
    for pipe in fit_candidates(tr, "daily").values():
        assert b"smdx_training" not in pickle.dumps(pipe)


def test_same_seed_gives_same_predictions(sample_dir):
    tr, va = time_split(build_training_table(load_folder(sample_dir), "daily", ["VEG"]))
    a = fit_candidates(tr, "daily", seed=42)["random_forest"].predict(va[DAILY_FEATURE_COLUMNS])
    b = fit_candidates(tr, "daily", seed=42)["random_forest"].predict(va[DAILY_FEATURE_COLUMNS])
    assert np.array_equal(a, b)
