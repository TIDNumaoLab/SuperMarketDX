"""学習用の表(詳細設計書「情報の時点」を学習データに当てはめる。「学習・評価・バックテスト」手順1)。"""
from datetime import timedelta

import pandas as pd
import pytest

from smdx_features.columns import DAILY_FEATURE_COLUMNS, TIME_BAND_FEATURE_COLUMNS
from smdx_training.dataset import DEFAULT_DEPARTMENTS, build_training_table, load_folder, time_split


def _daily_sold(raw, code, day) -> float:
    pos = raw.pos[(raw.pos.product_code == code) & (raw.pos.sales_date == day)]
    return float(pos.quantity.sum())


def test_load_folder_types(sample_dir):
    raw = load_folder(sample_dir)
    assert len(raw.products) == 15 and raw.products.can_carry_over.dtype == bool
    fresh = raw.pos[raw.pos.product_code.str.startswith("VEG")]
    assert fresh.sales_hour.isna().all()
    assert raw.pos[raw.pos.product_code.str.startswith("DELI")].sales_hour.notna().all()
    assert raw.weather.time.iloc[0].utcoffset() == timedelta(hours=9)
    assert set(raw.calendar.kind) <= {"holiday", "event"}
    assert raw.true_demand is not None and len(raw.true_demand) > 0


def test_default_departments():
    assert DEFAULT_DEPARTMENTS == {"daily": ["VEG", "FISH"], "time_band": ["DELI"]}


def test_training_table_columns_and_time_rule(sample_dir):
    raw = load_folder(sample_dir)
    t = build_training_table(raw, "daily", ["VEG", "FISH"])
    assert list(t.columns[: len(DAILY_FEATURE_COLUMNS)]) == DAILY_FEATURE_COLUMNS
    assert {"target_date", "quantity"} <= set(t.columns)
    assert set(t.product_code) == {p for p in raw.products.product_code if p.startswith(("VEG", "FISH"))}
    row = t[t.product_code == "VEG-001"].iloc[-1]
    # リードタイム1日: 計画日 = 対象日 − 1、基準日 = 対象日 − 2 なので、対象日の7日前の実績を使える
    assert row.sales_lag_7d == _daily_sold(raw, "VEG-001", row.target_date - timedelta(days=7))
    assert row.quantity == _daily_sold(raw, "VEG-001", row.target_date)


def test_first_14_days_are_excluded(sample_dir):
    raw = load_folder(sample_dir)
    t = build_training_table(raw, "daily", ["VEG"])
    first = raw.pos.sales_date.min()
    assert t.target_date.min() == first + timedelta(days=14)
    assert t.groupby("product_code").target_date.nunique().eq(120 - 14).all()


def test_time_band_table_rows(sample_dir):
    raw = load_folder(sample_dir)
    t = build_training_table(raw, "time_band", ["DELI"])
    assert list(t.columns[: len(TIME_BAND_FEATURE_COLUMNS)]) == TIME_BAND_FEATURE_COLUMNS
    assert set(t.time_band) == {10, 11, 14, 17}
    row = t[(t.product_code == "DELI-001") & (t.time_band == 11)].iloc[-1]
    pos = raw.pos[(raw.pos.product_code == "DELI-001") & (raw.pos.sales_date == row.target_date)]
    assert row.quantity == pos[(pos.sales_hour >= 11) & (pos.sales_hour < 14)].quantity.sum()


def test_time_split_last_28_days(sample_dir):
    tr, va = time_split(build_training_table(load_folder(sample_dir), "daily", ["VEG"]))
    assert va.target_date.nunique() == 28 and tr.target_date.max() < va.target_date.min()
    assert len(tr) + len(va) == (120 - 14) * 6


def test_unknown_department_rejected(sample_dir):
    with pytest.raises(ValueError, match="部門"):
        build_training_table(load_folder(sample_dir), "daily", ["NONE"])


def _drop_day(raw, day):
    from dataclasses import replace

    return replace(raw, pos=raw.pos[raw.pos.sales_date != day].reset_index(drop=True))


def test_day_without_any_pos_is_excluded(sample_dir):
    # POS が1行も無い日は未取込とみなし、学習・評価の対象日から外す(売上0として学習しない)
    raw = load_folder(sample_dir)
    gap = raw.pos.sales_date.max() - timedelta(days=10)
    t = build_training_table(_drop_day(raw, gap), "daily", ["VEG"])
    assert gap not in set(t.target_date)
    assert t.groupby("product_code").target_date.nunique().eq(120 - 14 - 1).all()
    # 前週同曜日に未取込日が当たる行は「実績なし」(0ではない)
    row = t[(t.product_code == "VEG-001") & (t.target_date == gap + timedelta(days=7))].iloc[0]
    assert pd.isna(row.sales_lag_7d)


def test_time_band_day_without_any_pos_is_excluded(sample_dir):
    raw = load_folder(sample_dir)
    gap = raw.pos.sales_date.max() - timedelta(days=10)
    t = build_training_table(_drop_day(raw, gap), "time_band", ["DELI"])
    assert gap not in set(t.target_date)
