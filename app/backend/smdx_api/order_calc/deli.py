"""惣菜(時間帯別)の製造数。

製造数(時間帯 t) = 切り上げ(max(0, 時間帯 t の予測 × 安全係数 − 陳列残数(t)))
陳列残数(t) = 入力時刻の直後の時間帯のみ、入力された陳列残数。それ以外の時間帯は0
前の時間帯の製造残を次の時間帯に繰り越す計算は行わない(陳列残数の入力で補正する)。
"""
import math
from collections.abc import Sequence
from datetime import time

_EPS = 1e-9


def display_stock_by_band(entered_at: time | None, quantity: int, bands: Sequence[int]) -> dict[int, int]:
    """開始時刻が入力時刻より後の最初の時間帯にだけ陳列残数を割り当てる。"""
    out = {b: 0 for b in bands}
    if entered_at is None:
        return out
    for b in sorted(bands):
        if time(b) > entered_at:
            out[b] = quantity
            break
    return out


def calc_deli_production(band_forecast: float, safety_factor: float, display_stock: int) -> int:
    need = band_forecast * safety_factor - display_stock
    return max(0, math.ceil(need - _EPS)) if need > 0 else 0
