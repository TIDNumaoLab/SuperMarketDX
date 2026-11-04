"""提案の操作の条件・期限経過の遷移・最新性判定。DB に依存しない。

操作の条件は詳細設計書「提案の状態遷移」、最新性判定は「自動再計算の対象と判定」に従う。
違反は StateError(API では 409)、入力の不備は InputError(422)。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from smdx_api.proposals.codes import BULK_EXCLUDED, Status


class StateError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InputError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ProposalState:
    status: Status
    is_adjusted: bool
    deadline: datetime
    warnings: tuple[str, ...]
    recalculated_qty: int | None


def check_adjust(s: ProposalState) -> None:
    if s.status == "approved":
        raise StateError("承認済みの提案は修正できません")
    if s.status != "pending":
        raise StateError("この提案は修正できません")


def check_order_unit(quantity: int, order_unit: int) -> None:
    """生鮮の数量修正は発注単位(入数)の倍数に限る(発注できない数量を承認させない)。"""
    if quantity % order_unit != 0:
        raise InputError(f"発注単位({order_unit})の倍数で入力してください")


EXPIRED_FOR_CANCEL = "期限を過ぎているため取り消せません"
QTY_CHANGED = "数量が更新されました。一覧を取り直してから承認してください"
BULK_QTY_CHANGED = "数量が更新されたため一括承認から除外しました"


def check_approve(s: ProposalState, confirm_warnings: bool, current_qty: int, expected_qty: int) -> None:
    """expected_qty は画面に表示していた提案数。裏の再計算で変わっていれば、見ていない数量を承認しないよう拒否する。"""
    if s.status != "pending":
        raise StateError("未承認の提案ではありません")
    if current_qty != expected_qty:
        raise StateError(QTY_CHANGED)
    if s.warnings and not confirm_warnings:
        raise InputError("警告を確認してください")


def bulk_skip_reason(s: ProposalState, current_qty: int, expected_qty: int) -> str | None:
    """一括承認で除外する理由。承認してよければ None。"""
    if s.status != "pending":
        return "未承認ではありません"
    if current_qty != expected_qty:
        return BULK_QTY_CHANGED
    if set(s.warnings) & BULK_EXCLUDED:
        return "警告があるため一括承認から除外しました"
    return None


def check_cancel(s: ProposalState, now: datetime) -> None:
    # 期限ちょうど以後は、操作の冒頭の期限経過の更新で確定になっている
    if s.status == "confirmed":
        raise StateError(EXPIRED_FOR_CANCEL)
    if s.status != "approved":
        raise StateError("承認済みの提案ではありません")
    if now >= s.deadline:
        raise StateError(EXPIRED_FOR_CANCEL)


def check_adopt(s: ProposalState, now: datetime) -> None:
    if s.recalculated_qty is None:
        raise StateError("再計算値がありません")
    if not (s.status == "pending" or (s.status == "approved" and now < s.deadline)):
        raise StateError("この提案には再計算値を採用できません")


def deadline_transition(s: ProposalState, now: datetime) -> Status | None:
    """期限(ちょうどを含む)を過ぎたときの遷移先。未承認は期限切れ、承認済みは確定。"""
    if now < s.deadline:
        return None
    if s.status == "pending":
        return "expired"
    if s.status == "approved":
        return "confirmed"
    return None


def is_protected(s: ProposalState) -> bool:
    """自動では数量を変えない提案(修正あり・承認取消後の未承認、承認済み)。"""
    return (s.status == "pending" and s.is_adjusted) or s.status == "approved"


@dataclass(frozen=True)
class FreshnessContext:
    # その部門の在庫・POSの取込、在庫の手入力、陳列残数の入力、提案の確定のうち最新の日時
    data_changed_at: datetime | None
    # 特売・カレンダーの最終変更日時(settings の internal.events_changed_at)
    events_changed_at: datetime | None
    # 計算に関わる設定の最終変更日時(settings の internal.settings_changed_at)
    settings_changed_at: datetime | None
    current_model_version: str
    stale_hours: float


@dataclass(frozen=True)
class ProposalFreshness:
    calculated_at: datetime
    model_version: str
    weather_fetched_at: datetime | None
    # 再計算値を採用した(数量と根拠が食い違っている)ため、次の判定で再計算する
    recalc_pending: bool = False


def is_stale(p: ProposalFreshness, ctx: FreshnessContext, now: datetime) -> bool:
    """作成済みの提案を再計算すべきか(未作成の判定は呼び出し側で行う)。

    予報なし(NO_WEATHER)で作った提案は予報の取得日時が無いため、計算した日時から判定時間が過ぎたら取り直す
    (すぐに「古い」とすると、予報が取れない間は画面を開くたびに再計算が続くため)。
    model_version は計算時に読み込んでいたモデルの版(行ごとにベースラインになったかどうかではない)。
    """
    if p.recalc_pending:
        return True
    if ctx.data_changed_at is not None and ctx.data_changed_at > p.calculated_at:
        return True
    if ctx.events_changed_at is not None and ctx.events_changed_at > p.calculated_at:
        return True
    if ctx.settings_changed_at is not None and ctx.settings_changed_at > p.calculated_at:
        return True
    if p.model_version != ctx.current_model_version:
        return True
    fetched = p.weather_fetched_at or p.calculated_at
    return now - fetched >= timedelta(hours=ctx.stale_hours)
