"""生鮮の発注数の計算(詳細設計書「発注数・製造数の計算(生鮮)」)。"""
from datetime import date, time

import pytest

from smdx_api.order_calc.fresh import (
    FreshInput,
    calc_fresh_order,
    ceil_to_unit,
    expected_sales,
    hourly_sales_ratio,
    remaining_sales_ratio,
)


def test_design_example_is_42():
    # 納品日の予測需要42.3、安全係数1.1、持越見込8、入数6 → 46.53 − 8 = 38.53 → 6の倍数に切り上げて 42
    r = calc_fresh_order(FreshInput(42.3, 0, 8, 0, True, 1.1, 6))
    assert r.required_qty == pytest.approx(46.53) and r.carry_over_qty == 8 and r.order_qty == 42


def test_ceil_to_unit_float_error():
    assert ceil_to_unit(1.1 * 30, 1) == 33          # 33.000000000000004 でも 34 にしない
    assert ceil_to_unit(36.0000000001, 6) == 36
    assert ceil_to_unit(36.1, 6) == 42
    assert ceil_to_unit(-3, 6) == 0
    assert ceil_to_unit(0, 6) == 0


def test_no_carry_over_product_ignores_inventory():
    assert calc_fresh_order(FreshInput(10, 0, 50, 0, False, 1.1, 1)).order_qty == 11


def test_backlog_and_expected_sales():
    r = calc_fresh_order(FreshInput(20, expected_sales_qty=15, inventory_qty=10, backlog_qty=12,
                                    can_carry_over=True, safety_factor=1.0, order_unit=1))
    assert r.carry_over_qty == 7 and r.order_qty == 13


def test_carry_over_never_negative():
    assert calc_fresh_order(FreshInput(10, 30, 5, 0, True, 1.0, 1)).carry_over_qty == 0


def test_missing_inventory_means_zero_carry():
    assert calc_fresh_order(FreshInput(10, 0, None, 5, True, 1.0, 1)).carry_over_qty == 0


def test_never_negative():
    assert calc_fresh_order(FreshInput(1, 0, 100, 0, True, 1.1, 6)).order_qty == 0


def test_expected_sales_with_middle_day():   # リードタイム2日: 基準日の残り + 途中の日1日
    assert expected_sales(30, 0.25, [28]) == pytest.approx(35.5)
    assert expected_sales(30, 0.0, []) == 0


@pytest.mark.parametrize("t,expected", [(time(9), 1.0), (time(10), 1.0), (time(15), 0.5), (time(20), 0.0), (time(21), 0.0)])
def test_remaining_ratio_by_business_hours(t, expected):
    assert remaining_sales_ratio(t, time(10), time(20), None) == pytest.approx(expected)


def test_remaining_ratio_by_hourly_share():
    ratio = {10: 0.1, 11: 0.2, 12: 0.3, 13: 0.4}
    assert remaining_sales_ratio(time(12, 30), time(10), time(20), ratio) == pytest.approx(0.15 + 0.4)
    assert remaining_sales_ratio(time(8), time(10), time(20), ratio) == 1.0
    assert remaining_sales_ratio(time(20, 30), time(10), time(20), ratio) == 0.0


def test_hourly_ratio_same_weekday_last_8_weeks():
    rows = [(date(2026, 10, 14), 10, 2), (date(2026, 10, 14), 11, 6), (date(2026, 10, 13), 10, 100),  # 10/13 は曜日違い
            (date(2026, 8, 12), 10, 100)]  # 9週前は対象外
    assert hourly_sales_ratio(rows, weekday=2, until=date(2026, 10, 15)) == {10: 0.25, 11: 0.75}
    assert hourly_sales_ratio([], 2, date(2026, 10, 15)) is None
    assert hourly_sales_ratio([(date(2026, 10, 16), 10, 5)], 4, date(2026, 10, 15)) is None  # until より後は使わない
