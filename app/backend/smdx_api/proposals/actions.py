"""提案の修正・承認・一括承認・取消・再計算値の採用(詳細設計書「提案の状態遷移」)。

いずれも先頭で期限経過の状態更新(個別の操作では提案の部門に限る)を行い、対象の行を FOR UPDATE で読み直してから
条件を確かめる。条件の違反は StateError(409)、入力の不備は InputError(422)。操作のたびに proposal_histories に記録する。
条件の確認は提案を変える前に行う。違反のとき、呼び出し側は期限経過の更新だけを確定できる。
"""
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.db.models import Proposal, ProposalHistory
from smdx_api.proposals.deadlines import apply_deadlines, state_of
from smdx_api.proposals.rules import (
    bulk_skip_reason,
    check_adjust,
    check_adopt,
    check_approve,
    check_cancel,
    check_order_unit,
)

NOT_FOUND = "対象が見つかりません"
# 根拠(basis)に付ける再計算待ちの印
RECALC_PENDING = "recalc_pending"


class ProposalNotFound(Exception):
    pass


def _lock(db: Session, proposal_id: int) -> Proposal | None:
    return db.scalar(select(Proposal).where(Proposal.id == proposal_id).with_for_update()
                     .execution_options(populate_existing=True))


def _get(db: Session, proposal_id: int, now: datetime) -> Proposal:
    department_id = db.scalar(select(Proposal.department_id).where(Proposal.id == proposal_id))
    if department_id is None:
        raise ProposalNotFound(proposal_id)
    apply_deadlines(db, now, department_id)
    p = _lock(db, proposal_id)
    if p is None:
        raise ProposalNotFound(proposal_id)
    return p


def _history(db: Session, p: Proposal, action: str, actor_id: int | None, now: datetime, before: int | None,
             after: int | None, reason: str | None = None) -> None:
    db.add(ProposalHistory(proposal_id=p.id, action=action, actor_id=actor_id, qty_before=before, qty_after=after,
                           reason=reason, occurred_at=now))
    db.flush()


def adjust(db: Session, proposal_id: int, quantity: int, reason: str, note: str | None, actor_id: int,
           now: datetime) -> Proposal:
    p = _get(db, proposal_id, now)
    check_adjust(state_of(p))
    # 惣菜の製造数は発注単位で丸めないため、生鮮の部門だけ確かめる
    if p.department.business_type == "order":
        check_order_unit(quantity, p.product.order_unit)
    before = p.proposed_qty
    p.proposed_qty, p.is_adjusted, p.adjust_reason, p.adjust_note = quantity, True, reason, note
    _history(db, p, "adjust", actor_id, now, before, quantity, reason)
    return p


def _approve(db: Session, p: Proposal, actor_id: int, now: datetime) -> None:
    p.status, p.approved_by, p.approved_at = "approved", actor_id, now
    _history(db, p, "approve", actor_id, now, p.proposed_qty, p.proposed_qty)


def approve(db: Session, proposal_id: int, expected_qty: int, confirm_warnings: bool, actor_id: int,
            now: datetime) -> Proposal:
    p = _get(db, proposal_id, now)
    check_approve(state_of(p), confirm_warnings, p.proposed_qty, expected_qty)
    _approve(db, p, actor_id, now)
    return p


def approve_bulk(db: Session, items: Sequence[tuple[int, int]], actor_id: int,
                 now: datetime) -> tuple[list[int], list[tuple[int, str]]]:
    """pending かつ警告なしで、表示していた数量のままの提案だけを承認する。除外した ID と理由を返す(エラーにしない)。

    items は (提案ID, 画面に表示していた提案数)。同じ ID が重なれば最初のものを使う。
    """
    apply_deadlines(db, now)
    expected: dict[int, int] = {}
    for proposal_id, qty in items:
        expected.setdefault(proposal_id, qty)
    approved, skipped = [], []
    # 2人が重なる提案を同時に一括承認しても行き詰まらないよう、ID の小さい順にロックする
    for proposal_id, qty in sorted(expected.items()):
        p = _lock(db, proposal_id)
        if p is None:
            skipped.append((proposal_id, NOT_FOUND))
            continue
        reason = bulk_skip_reason(state_of(p), p.proposed_qty, qty)
        if reason is not None:
            skipped.append((proposal_id, reason))
            continue
        _approve(db, p, actor_id, now)
        approved.append(proposal_id)
    return approved, skipped


def cancel_approval(db: Session, proposal_id: int, actor_id: int, now: datetime) -> Proposal:
    """期限前の承認を取り消す。修正ありとして扱い、以後は自動では数量を変えない。"""
    p = _get(db, proposal_id, now)
    check_cancel(state_of(p), now)
    p.status, p.is_adjusted, p.approved_by, p.approved_at = "pending", True, None, None
    _history(db, p, "cancel", actor_id, now, p.proposed_qty, p.proposed_qty)
    return p


def adopt_recalculated(db: Session, proposal_id: int, actor_id: int, now: datetime) -> Proposal:
    """再計算値を提案値として採用し、未承認・修正なしに戻す。修正前の値と修正理由は履歴に残す。

    根拠は採用前の計算のもので数量と食い違うため、根拠に再計算待ちの印を付けて次の最新性判定で再計算させる。
    """
    p = _get(db, proposal_id, now)
    check_adopt(state_of(p), now)
    _history(db, p, "adopt", actor_id, now, p.proposed_qty, p.recalculated_qty, p.adjust_reason)
    p.proposed_qty = p.original_qty = p.recalculated_qty
    p.recalculated_qty = None
    p.adjust_reason = p.adjust_note = None
    p.approved_by = p.approved_at = None
    p.status, p.is_adjusted = "pending", False
    p.basis = {**(p.basis or {}), RECALC_PENDING: True}
    db.flush()
    return p
