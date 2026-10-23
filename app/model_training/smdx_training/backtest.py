"""バックテスト: 検証期間について、予測+本体の計算式で日々発注・製造した場合の廃棄数・欠品数を、在庫を引き継ぎながら模擬する。

- 生鮮: 前日閉店時の在庫を見て発注し、翌日開店時に納品する(発注残・販売見込は0。詳細設計書「学習・評価・バックテスト」手順6)。
  持越可の商品は売れ残りを翌日の在庫に、持越不可は全数廃棄。
- 惣菜: 時間帯ごとに製造(陳列残数0)。前の時間帯の売れ残りは同じ日の次の時間帯で売れ、閉店時の残りは全数廃棄。
需要は真の需要があればそれを使い、無ければ販売数を需要とみなす(欠品時に販売数が打ち切られるため欠品数は過小評価)。
計算式は本体の order_calc をそのまま使う。
"""
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from smdx_api.order_calc.deli import calc_deli_production
from smdx_api.order_calc.fresh import FreshInput, calc_fresh_order
from smdx_features.columns import Granularity

DEFAULT_SAFETY_FACTOR = 1.1


@dataclass(frozen=True)
class BacktestResult:
    waste_qty: int
    stockout_qty: int
    # 原価・売価がある場合の金額換算(廃棄 × 原価、欠品 × 売価)。無い商品があれば None
    waste_amount: float | None
    stockout_amount: float | None
    uses_true_demand: bool


def _demand_lookup(valid: pd.DataFrame, demand: pd.DataFrame | None, granularity: Granularity) -> dict[tuple, float]:
    if demand is None:
        keys = zip(valid.product_code, valid.target_date, valid.time_band) if granularity == "time_band" else zip(
            valid.product_code, valid.target_date)
        return {k: float(q) for k, q in zip(keys, valid.quantity)}
    if granularity == "time_band":
        d = demand[demand.time_band.notna()]
        return {(c, day, int(b)): float(q) for c, day, b, q in zip(d.product_code, d.date, d.time_band, d.demand)}
    d = demand[demand.time_band.isna()]
    return {(c, day): float(q) for c, day, q in zip(d.product_code, d.date, d.demand)}


def run_backtest(
    valid: pd.DataFrame,
    predicted: np.ndarray,
    demand: pd.DataFrame | None,
    products: pd.DataFrame,
    granularity: Granularity,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
) -> BacktestResult:
    lookup = _demand_lookup(valid, demand, granularity)
    info = products.set_index("product_code")
    pred = np.asarray(predicted, dtype=float)
    waste: dict[str, int] = {}
    stockout: dict[str, int] = {}

    frame = valid.assign(_pred=pred)
    if granularity == "daily":
        for code, rows in frame.sort_values("target_date").groupby("product_code", sort=True):
            p = info.loc[code]
            carry_ok = bool(p.can_carry_over)
            closing = 0
            w = so = 0
            for day, f in zip(rows.target_date, rows._pred):
                order = calc_fresh_order(FreshInput(float(f), 0.0, closing if carry_ok else None, 0, carry_ok,
                                                    safety_factor, int(p.order_unit))).order_qty
                stock = (closing if carry_ok else 0) + order
                dem = lookup.get((code, day), 0.0)
                sold = min(dem, stock)
                so += int(round(dem - sold))
                left = int(round(stock - sold))
                if carry_ok:
                    closing = left
                else:
                    w += left
                    closing = 0
            waste[code], stockout[code] = w, so
    else:
        for (code, day), rows in frame.sort_values(["target_date", "time_band"]).groupby(["product_code", "target_date"], sort=True):
            left = 0
            w, so = waste.get(code, 0), stockout.get(code, 0)
            for band, f in zip(rows.time_band, rows._pred):
                available = calc_deli_production(float(f), safety_factor, 0) + left
                dem = lookup.get((code, day, int(band)), 0.0)
                sold = min(dem, available)
                so += int(round(dem - sold))
                left = int(round(available - sold))
            waste[code], stockout[code] = w + left, so

    has_prices = all(pd.notna(info.loc[c, "cost_price"]) and pd.notna(info.loc[c, "selling_price"]) for c in waste)
    return BacktestResult(
        waste_qty=sum(waste.values()),
        stockout_qty=sum(stockout.values()),
        waste_amount=float(sum(waste[c] * info.loc[c, "cost_price"] for c in waste)) if has_prices else None,
        stockout_amount=float(sum(stockout[c] * info.loc[c, "selling_price"] for c in stockout)) if has_prices else None,
        uses_true_demand=demand is not None,
    )
