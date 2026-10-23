"""バックテスト(詳細設計書「学習・評価・バックテスト」手順6)。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from smdx_training.backtest import run_backtest

D0 = date(2026, 10, 1)


def products_df(cost=200.0, price=348.0) -> pd.DataFrame:
    return pd.DataFrame({
        "product_code": ["FISH-001", "VEG-001", "DELI-001"],
        "department_code": ["FISH", "VEG", "DELI"],
        "order_unit": [1, 6, 1],
        "lead_time_days": [1, 1, 0],
        "can_carry_over": [False, True, False],
        "cost_price": [cost, 98.0, 180.0],
        "selling_price": [price, 158.0, 398.0],
    })


def valid_rows(code: str, n: int) -> pd.DataFrame:
    return pd.DataFrame({"product_code": [code] * n, "target_date": [D0 + timedelta(days=i) for i in range(n)],
                         "quantity": [0.0] * n})


def demand_rows(code: str, demands: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"date": [D0 + timedelta(days=i) for i in range(len(demands))],
                         "time_band": pd.array([None] * len(demands), dtype="Int64"),
                         "product_code": [code] * len(demands), "demand": demands})


def test_backtest_fresh_waste_and_stockout():
    # FISH-001(入数1・持越不可)、需要 [10, 10, 30]、予測 [10, 10, 10]、安全係数1.1
    # 発注 11 → 廃棄 1, 1, 0、欠品 0, 0, 19
    r = run_backtest(valid_rows("FISH-001", 3), np.array([10, 10, 10.0]), demand_rows("FISH-001", [10, 10, 30]),
                     products_df(), "daily")
    assert (r.waste_qty, r.stockout_qty, r.uses_true_demand) == (2, 19, True)


def test_backtest_carry_over_reduces_next_order():
    # VEG-001(入数6・持越可)、需要 [5, 5, 5]、予測 [5, 5, 5]
    # 1日目 必要5.5 → 6 発注、売れ残り1を持越 → 2日目 5.5−1=4.5 → 6 発注(在庫7)、残り2 → 3日目 5.5−2=3.5 → 6(在庫8)、残り3
    # 持越可なので廃棄0。欠品も0
    r = run_backtest(valid_rows("VEG-001", 3), np.array([5, 5, 5.0]), demand_rows("VEG-001", [5, 5, 5]), products_df(), "daily")
    assert (r.waste_qty, r.stockout_qty) == (0, 0)
    # 持越が効かないと3日目に在庫が溜まらない: 予測0なら発注0 → 全日欠品
    r0 = run_backtest(valid_rows("VEG-001", 3), np.array([0, 0, 0.0]), demand_rows("VEG-001", [5, 5, 5]), products_df(), "daily")
    assert r0.stockout_qty == 15


def test_backtest_amounts_use_cost_and_price():
    r = run_backtest(valid_rows("FISH-001", 3), np.array([10, 10, 10.0]), demand_rows("FISH-001", [10, 10, 30]),
                     products_df(), "daily")
    assert r.waste_amount == pytest.approx(2 * 200) and r.stockout_amount == pytest.approx(19 * 348)


def test_backtest_amounts_none_without_prices():
    r = run_backtest(valid_rows("FISH-001", 1), np.array([10.0]), demand_rows("FISH-001", [10]),
                     products_df(cost=np.nan, price=np.nan), "daily")
    assert r.waste_amount is None and r.stockout_amount is None


def test_backtest_without_true_demand_uses_sales():
    v = valid_rows("FISH-001", 2)
    v["quantity"] = [10.0, 30.0]
    r = run_backtest(v, np.array([10, 10.0]), None, products_df(), "daily")
    assert (r.waste_qty, r.stockout_qty, r.uses_true_demand) == (1, 19, False)


def test_backtest_deli_bands_carry_within_day_and_waste_at_close():
    # DELI-001: 予測 各帯 10 → 製造 11。需要 10時帯 5、11時帯 20、14時帯 10、17時帯 10
    # 10時帯: 11 で 5 売れて 6 残る → 11時帯: 11+6=17 で 17 売れ 欠品3 → 14時帯: 11 で 10、残り1 → 17時帯: 12 で 10、残り2 → 廃棄2
    v = pd.DataFrame({"product_code": ["DELI-001"] * 4, "target_date": [D0] * 4, "time_band": [10, 11, 14, 17],
                      "quantity": [0.0] * 4})
    d = pd.DataFrame({"date": [D0] * 4, "time_band": pd.array([10, 11, 14, 17], dtype="Int64"),
                      "product_code": ["DELI-001"] * 4, "demand": [5, 20, 10, 10]})
    r = run_backtest(v, np.array([10, 10, 10, 10.0]), d, products_df(), "time_band")
    assert (r.waste_qty, r.stockout_qty) == (2, 3)
