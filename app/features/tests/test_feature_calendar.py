from datetime import date

import pytest

from smdx_features.calendar import CalendarFlags, calendar_flags

# 2026-09-19(土)〜23(水)の5連休
HOL = {date(2026, 9, 21): "敬老の日", date(2026, 9, 22): "国民の休日", date(2026, 9, 23): "秋分の日"}


@pytest.mark.parametrize("day,seq", [
    (date(2026, 9, 19), 1),
    (date(2026, 9, 21), 3),
    (date(2026, 9, 23), 5),
    (date(2026, 9, 26), 0),   # 普通の土曜(2日だけの休み)は連休にしない(詳細設計書「特徴量」の連休)
    (date(2026, 9, 24), 0),   # 平日
    (date(2026, 9, 18), 0),
])
def test_holiday_seq(day, seq):
    assert calendar_flags(day, HOL, {}).holiday_seq == seq


def test_three_day_weekend_with_monday_holiday():
    hol = {date(2026, 10, 12): "スポーツの日"}
    assert [calendar_flags(date(2026, 10, d), hol, {}).holiday_seq for d in (10, 11, 12, 13)] == [1, 2, 3, 0]


def test_holiday_and_event_flags():
    f = calendar_flags(date(2026, 7, 24), {}, {date(2026, 7, 24): "土用の丑の日"})
    assert f == CalendarFlags(is_holiday=False, is_event_day=True, holiday_seq=0, holiday_name="土用の丑の日")


def test_holiday_name_prefers_holiday():
    d = date(2026, 1, 1)
    f = calendar_flags(d, {d: "元日"}, {d: "初売り"})
    assert (f.is_holiday, f.is_event_day, f.holiday_name) == (True, True, "元日")


def test_plain_day():
    assert calendar_flags(date(2026, 10, 14), {}, {}) == CalendarFlags(False, False, 0, None)
