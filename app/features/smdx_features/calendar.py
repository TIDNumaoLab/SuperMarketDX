"""曜日・祝日・行事日・連休の特徴量。

連休 = 土・日・祝日が3日以上続く期間。holiday_seq はその何日目か(1始まり)、連休でなければ0(詳細設計書「特徴量」)。
毎週の土日(2日)は連休としない。
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

MIN_LONG_HOLIDAY_DAYS = 3


@dataclass(frozen=True)
class CalendarFlags:
    is_holiday: bool
    is_event_day: bool
    holiday_seq: int
    # 祝日名(無ければ行事日名)。根拠の表示用
    holiday_name: str | None


def _is_day_off(d: date, holidays: Mapping[date, str]) -> bool:
    return d.weekday() >= 5 or d in holidays


def calendar_flags(day: date, holidays: Mapping[date, str], events: Mapping[date, str]) -> CalendarFlags:
    seq = 0
    if _is_day_off(day, holidays):
        start = day
        while _is_day_off(start - timedelta(days=1), holidays):
            start -= timedelta(days=1)
        end = day
        while _is_day_off(end + timedelta(days=1), holidays):
            end += timedelta(days=1)
        if (end - start).days + 1 >= MIN_LONG_HOLIDAY_DAYS:
            seq = (day - start).days + 1
    return CalendarFlags(
        is_holiday=day in holidays,
        is_event_day=day in events,
        holiday_seq=seq,
        holiday_name=holidays.get(day) or events.get(day),
    )
