"""候補アルゴリズムの学習(ランダムフォレスト、勾配ブースティング)。

前処理は商品コードを順序の番号に置き換え、他の列(曜日・時間帯・天候コードを含む)は数値として扱い、
欠損は中央値で補う。決定木系のモデルなのでカテゴリを番号で扱っても分割で表せる。
パイプラインは scikit-learn・LightGBM の部品だけで作る(本体が smdx_training なしで読み込めるようにするため)。
"""
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

import pandas as pd

from smdx_features.columns import Granularity, feature_columns

SEED = 42


def _preprocess(granularity: Granularity) -> ColumnTransformer:
    cols = feature_columns(granularity)
    numeric = [c for c in cols if c != "product_code"]
    return ColumnTransformer([
        ("product", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["product_code"]),
        ("numeric", SimpleImputer(strategy="median"), numeric),
    ])


def make_candidates(granularity: Granularity, seed: int = SEED) -> dict[str, Pipeline]:
    return {
        "random_forest": Pipeline([
            ("prep", _preprocess(granularity)),
            ("model", RandomForestRegressor(n_estimators=300, random_state=seed, n_jobs=-1)),
        ]),
        "lightgbm": Pipeline([
            ("prep", _preprocess(granularity)),
            # n_jobs=-1 は論理コア数で動かす(省略すると物理コア数を調べ、Windows では長いエラーを表示する)
            ("model", LGBMRegressor(n_estimators=500, learning_rate=0.05, random_state=seed, verbose=-1, n_jobs=-1)),
        ]),
    }


def fit_candidates(train: pd.DataFrame, granularity: Granularity, seed: int = SEED) -> dict[str, Pipeline]:
    X, y = train[feature_columns(granularity)], train["quantity"].astype(float)
    models = make_candidates(granularity, seed)
    for pipe in models.values():
        pipe.fit(X, y)
    return models
