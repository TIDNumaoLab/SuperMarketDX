from datetime import date

import pytest

from smdx_features.sales import SalesSeries, base_date, sales_avg_7d, sales_lag_7d


def s(rows):
    return SalesSeries.from_rows([(date.fromisoformat(d), q) for d, q in rows])


def test_base_date_is_day_before_plan():
    assert base_date(date(2026, 10, 16)) == date(2026, 10, 15)


def test_lag_uses_target_minus_7_when_known():
    ser = s([("2026-10-08", 5), ("2026-10-14", 9)])
    assert sales_lag_7d(ser, date(2026, 10, 15), base=date(2026, 10, 14)) == 5


def test_lag_steps_back_when_after_base():
    # リードタイム2日: 計画日 10/13、基準日 10/12、対象日 10/20 → 10/13 は基準日より後 → 10/06 を使う
    ser = s([("2026-10-06", 4), ("2026-10-13", 99)])
    assert sales_lag_7d(ser, date(2026, 10, 20), base=date(2026, 10, 12)) == 4


def test_lag_steps_back_multiple_weeks():
    ser = s([("2026-09-29", 3), ("2026-10-06", 99), ("2026-10-13", 99)])
    assert sales_lag_7d(ser, date(2026, 10, 20), base=date(2026, 10, 5)) == 3


def test_zero_filled_days_and_no_history():
    ser = s([("2026-10-01", 3), ("2026-10-05", 2)])
    assert ser.first_day == date(2026, 10, 1)
    assert ser.value(date(2026, 10, 3)) == 0
    assert ser.value(date(2026, 9, 30)) is None
    assert sales_lag_7d(s([]), date(2026, 10, 15), date(2026, 10, 13)) is None
    assert s([]).first_day is None


def test_duplicate_days_are_summed():
    assert s([("2026-10-01", 3), ("2026-10-01", 2)]).value(date(2026, 10, 1)) == 5


def test_avg_uses_only_days_since_first_sale():
    ser = s([("2026-10-12", 6), ("2026-10-13", 2)])
    assert sales_avg_7d(ser, date(2026, 10, 13)) == 4
    assert sales_avg_7d(s([("2026-10-14", 1)]), date(2026, 10, 13)) is None


def test_avg_full_window_with_zero_days():
    ser = s([("2026-10-01", 7), ("2026-10-10", 7)])  # 10/04〜10/10 のうち売れたのは 10/10 だけ
    assert sales_avg_7d(ser, date(2026, 10, 10)) == pytest.approx(1.0)


def test_missing_days_are_unknown_not_zero():
    # POS が1行も無い日(未取込日)は「売上0」ではなく「実績なし」
    ser = SalesSeries.from_rows([(date(2026, 10, 1), 3), (date(2026, 10, 5), 2)], missing_days={date(2026, 10, 3)})
    assert ser.value(date(2026, 10, 3)) is None
    assert ser.value(date(2026, 10, 4)) == 0


def test_avg_skips_missing_days():
    rows = [(date(2026, 10, d), 7) for d in range(1, 11) if d != 9]
    ser = SalesSeries.from_rows(rows, missing_days={date(2026, 10, 9)})
    assert sales_avg_7d(ser, date(2026, 10, 10)) == pytest.approx(7.0)   # 10/09 を除いた6日で平均する
