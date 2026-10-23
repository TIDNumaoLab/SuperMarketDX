"""惣菜の製造数の計算(詳細設計書「発注数・製造数の計算(惣菜)」)。"""
from datetime import time

from smdx_api.order_calc.deli import calc_deli_production, display_stock_by_band

BANDS = [10, 11, 14, 17]


def test_display_stock_only_next_band():
    assert display_stock_by_band(time(10, 30), 5, BANDS) == {10: 0, 11: 5, 14: 0, 17: 0}
    assert display_stock_by_band(time(11, 0), 5, BANDS) == {10: 0, 11: 0, 14: 5, 17: 0}   # ちょうどは次の帯
    assert display_stock_by_band(time(9, 0), 5, BANDS) == {10: 5, 11: 0, 14: 0, 17: 0}    # 開店前
    assert display_stock_by_band(time(18, 0), 5, BANDS) == {10: 0, 11: 0, 14: 0, 17: 0}   # 最後の帯の開始以降
    assert display_stock_by_band(None, 5, [10, 11]) == {10: 0, 11: 0}


def test_deli_production():
    assert calc_deli_production(10, 1.1, 0) == 11
    assert calc_deli_production(10, 1.1, 4) == 7
    assert calc_deli_production(3, 1.1, 10) == 0
    assert calc_deli_production(30, 1.1, 0) == 33   # 浮動小数の誤差で 34 にしない
