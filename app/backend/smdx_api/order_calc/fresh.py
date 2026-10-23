"""生鮮(日別)の発注数。

販売見込 = 在庫基準日時から納品時刻までの予測販売数
         = 基準日の残り分(日別予測 × 残り営業時間の売上構成比)+ 途中の日の日別予測
持越見込 = max(0, 在庫数 + 発注残 − 販売見込)   ※持越不可の商品・在庫が無い場合は0
必要数   = カバー期間の予測需要 × 安全係数
発注数   = 発注単位で切り上げ(max(0, 必要数 − 持越見込))
"""
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta

# 浮動小数の誤差(1.1 × 30 = 33.000000000000004 など)で単位がひとつ増えないための許容幅
_EPS = 1e-9
HOURLY_RATIO_WEEKS = 8


def ceil_to_unit(qty: float, unit: int) -> int:
    """発注単位(入数)の倍数へ切り上げる。0以下は0。"""
    if qty <= 0:
        return 0
    return math.ceil(qty / unit - _EPS) * unit


def hourly_sales_ratio(
    rows: Iterable[tuple[date, int, float]], weekday: int, until: date, weeks: int = HOURLY_RATIO_WEEKS
) -> dict[int, float] | None:
    """直近 weeks 週間の同じ曜日の時刻つきPOS(販売日, 時, 数量)から、1時間ごとの売上の比率。行が無ければ None。"""
    since = until - timedelta(weeks=weeks)
    totals: dict[int, float] = {}
    for d, hour, qty in rows:
        if d.weekday() == weekday and since < d <= until:
            totals[hour] = totals.get(hour, 0.0) + float(qty)
    total = sum(totals.values())
    if total <= 0:
        return None
    return {h: q / total for h, q in sorted(totals.items())}


def _hours(t: time) -> float:
    return t.hour + t.minute / 60


def remaining_sales_ratio(
    based_at: time, open_: time, close: time, hourly_ratio: Mapping[int, float] | None
) -> float:
    """在庫基準時刻から閉店までに売れる割合。開店前は1、閉店後は0(詳細設計書「生鮮(日別)」の売上構成比)。

    時刻つきPOSの比率があれば、基準時刻の時の比率 × (60 − 分)/60 + それより後の時の比率の合計。
    無ければ営業時間の比率(残り営業時間 ÷ 営業時間)で代用する。
    """
    if based_at <= open_:
        return 1.0
    if based_at >= close:
        return 0.0
    if hourly_ratio is None:
        return min(1.0, max(0.0, (_hours(close) - _hours(based_at)) / (_hours(close) - _hours(open_))))
    current = hourly_ratio.get(based_at.hour, 0.0) * (60 - based_at.minute) / 60
    later = sum(r for h, r in hourly_ratio.items() if h > based_at.hour)
    return min(1.0, current + later)


def expected_sales(base_day_forecast: float, remaining_ratio: float, middle_day_forecasts: Sequence[float]) -> float:
    return base_day_forecast * remaining_ratio + sum(middle_day_forecasts)


@dataclass(frozen=True)
class FreshInput:
    # カバー期間(毎日納品なら納品日1日)の予測需要
    demand_forecast: float
    # 在庫基準日時から納品時刻までの販売見込
    expected_sales_qty: float
    # 在庫数(当日分が無ければ None。持越見込0で計算する)
    inventory_qty: int | None
    backlog_qty: int
    can_carry_over: bool
    safety_factor: float
    order_unit: int


@dataclass(frozen=True)
class FreshResult:
    order_qty: int
    carry_over_qty: float
    required_qty: float


def calc_fresh_order(inp: FreshInput) -> FreshResult:
    if inp.can_carry_over and inp.inventory_qty is not None:
        carry = max(0.0, inp.inventory_qty + inp.backlog_qty - inp.expected_sales_qty)
    else:
        carry = 0.0
    required = inp.demand_forecast * inp.safety_factor
    return FreshResult(order_qty=ceil_to_unit(max(0.0, required - carry), inp.order_unit), carry_over_qty=carry,
                       required_qty=required)
