"""実績系の特徴量(前週同曜日・直近7日平均)と、情報の時点の規則。

詳細設計書「情報の時点」: 発注・計画作成の時点で確定している実績だけを使う。基準日 = 計画日の前日。
sales_avg_7d は基準日から遡る7日の平均。sales_lag_7d は対象日の7日前の実績で、それが基準日より後なら
基準日以前で最も近い同じ曜日の実績を使う。
販売の無い日は POS に行が無いため、最初の販売日以降の日は0とみなす。最初の販売日より前は「実績なし」(詳細設計書「特徴量」)。
ただし未取込日(POS が1行も無い日)は0とみなさず「実績なし」とする(詳細設計書「欠損時の扱い」)。
"""
from collections.abc import Collection, Iterable
from datetime import date, timedelta

WINDOW_DAYS = 7


def base_date(plan_date: date) -> date:
    return plan_date - timedelta(days=1)


class SalesSeries:
    def __init__(self, by_day: dict[date, float], missing_days: Collection[date] = ()) -> None:
        self._by_day = by_day
        self._missing = frozenset(missing_days)
        self.first_day: date | None = min(by_day) if by_day else None

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[date, float]], missing_days: Collection[date] = ()) -> "SalesSeries":
        by_day: dict[date, float] = {}
        for d, q in rows:
            by_day[d] = by_day.get(d, 0.0) + float(q)
        return cls(by_day, missing_days)

    def value(self, day: date) -> float | None:
        if self.first_day is None or day < self.first_day or day in self._missing:
            return None
        return self._by_day.get(day, 0.0)


def sales_lag_7d(s: SalesSeries, target: date, base: date) -> float | None:
    d = target - timedelta(days=7)
    while d > base:
        d -= timedelta(days=7)
    return s.value(d)


def sales_avg_7d(s: SalesSeries, base: date) -> float | None:
    """基準日から遡る7日のうち、最初の販売日以降の日(未取込日を除く)だけで平均する(詳細設計書「特徴量」)。"""
    values = [v for i in range(WINDOW_DAYS) if (v := s.value(base - timedelta(days=i))) is not None]
    return sum(values) / len(values) if values else None
