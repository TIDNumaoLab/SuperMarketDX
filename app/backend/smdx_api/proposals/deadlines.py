"""期限経過による状態更新。定時処理は持たず、提案を読み出す処理の冒頭でまとめて行う(詳細設計書「提案の状態遷移」)。"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.db.models import Product, Proposal, ProposalHistory
from smdx_api.proposals.rules import ProposalState, deadline_transition

_ACTIONS = {"expired": "expire", "confirmed": "confirm"}


def state_of(p: Proposal) -> ProposalState:
    return ProposalState(p.status, p.is_adjusted, p.deadline, tuple(p.warnings or ()), p.recalculated_qty)


def apply_deadlines(db: Session, now: datetime, department_id: int | None = None) -> int:
    """期限(ちょうどを含む)を過ぎた未承認を期限切れ、承認済みを確定にし、履歴を操作者なしで残す。件数を返す。"""
    q = select(Proposal).where(Proposal.status.in_(("pending", "approved")), Proposal.deadline <= now)
    if department_id is not None:
        q = q.where(Proposal.department_id == department_id)
    changed = 0
    for p in db.scalars(q.order_by(Proposal.id).with_for_update()):
        to = deadline_transition(state_of(p), now)
        if to is None:
            continue
        p.status = to
        db.add(ProposalHistory(proposal_id=p.id, action=_ACTIONS[to], actor_id=None, qty_before=p.proposed_qty,
                               qty_after=p.proposed_qty, occurred_at=now))
        changed += 1
    db.flush()
    return changed


def expire_moved_products(db: Session, product_ids: list[int], now: datetime) -> int:
    """部門を移した商品について、今の部門以外に残る未確定(未承認・承認済み)の提案を期限切れにし、履歴を操作者なしで残す。

    商品マスタの取込の保存後に呼ぶ。旧部門の担当者が承認・発注できないようにする(新しい部門では次の最新性判定で作成する)。
    """
    q = (select(Proposal).join(Product, Proposal.product_id == Product.id)
         .where(Proposal.product_id.in_(product_ids), Proposal.status.in_(("pending", "approved")),
                Proposal.department_id != Product.department_id)
         .order_by(Proposal.id).with_for_update(of=Proposal))
    changed = 0
    for p in db.scalars(q):
        p.status = "expired"
        db.add(ProposalHistory(proposal_id=p.id, action="expire", actor_id=None, qty_before=p.proposed_qty,
                               qty_after=p.proposed_qty, occurred_at=now))
        changed += 1
    db.flush()
    return changed
