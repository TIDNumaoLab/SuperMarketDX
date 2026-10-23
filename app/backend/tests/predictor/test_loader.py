"""モデルファイルの適合確認(詳細設計書「ベースラインへの切替条件」)。"""
import numpy as np
import pytest

from smdx_api.predictor.loader import ModelIncompatible, check_model_object, load_model_file
from tests.predictor.conftest import ConstModel, model_dict


class OneRow:
    def predict(self, X):
        return np.zeros(1)


class NaNModel:
    def predict(self, X):
        return np.full(len(X), np.nan)


class Broken:
    def predict(self, X):
        raise ValueError("壊れた推論器")


@pytest.mark.parametrize("obj,reason", [
    ({"meta": {}}, "必須キーがありません: model"),
    ("not a dict", "必須キーがありません: model"),
    ({"model": ConstModel(1)}, "必須キーがありません: meta"),
    (model_dict(meta={"version": None}) | {"meta": {k: v for k, v in model_dict()["meta"].items() if k != "version"}},
     "必須キーがありません: meta.version"),
    (model_dict(meta={"granularity": "time_band"}), "granularity が部門と合いません"),
    (model_dict(meta={"feature_columns": ["product_code"]}), "feature_columns が本体の特徴量と一致しません"),
    (model_dict(model=object()), "試験入力での推論に失敗しました"),
    (model_dict(model=Broken()), "試験入力での推論に失敗しました"),
    (model_dict(model=OneRow()), "出力の行数が入力と一致しません"),
    (model_dict(model=NaNModel()), "出力に数値でない値が含まれます"),
])
def test_check_model_failures(obj, reason):
    with pytest.raises(ModelIncompatible, match=reason):
        check_model_object(obj, "daily")


def test_check_model_ok():
    loaded = check_model_object(model_dict("time_band"), "time_band")
    assert (loaded.version, loaded.granularity, loaded.time_bands) == ("time_band-2026.11.01-1", "time_band", [10, 11, 14, 17])


def test_missing_and_unreadable_files(tmp_path):
    with pytest.raises(ModelIncompatible, match="モデルファイルがありません"):
        load_model_file(tmp_path / "none.joblib", "daily")
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not joblib")
    with pytest.raises(ModelIncompatible, match="モデルファイルを読み込めません"):
        load_model_file(bad, "daily")
