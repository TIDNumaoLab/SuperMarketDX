"""取込の実行(詳細設計書「標準取込形式」「自動再計算の対象と判定」)。終了日時・順番待ち・部門を移した商品の扱い。"""

import pytest
from sqlalchemy import func, select, text

from smdx_api.db.models import ImportLog, Product, Proposal, ProposalHistory
from smdx_api.imports import service
from smdx_api.imports.service import IMPORT_LOCK_KEY, run_import
from tests.conftest import FixedClock, dept, jst

POS_CSV = b"sales_date,sales_time,product_code,quantity\n2026-10-15,10:00,VEG-001,3\n"
PRODUCTS_HEADER = "product_code,product_name,department_code,order_unit,lead_time_days,can_carry_over\n"


@pytest.mark.db
def test_finished_at_is_after_saving(db, product_factory, monkeypatch):
    """終了日時は保存し終えた時刻。要求を受けた時刻にすると、取込中に始まった計算の提案が最新と判定される。"""
    product_factory(code="VEG-001")
    clock = FixedClock(jst(2026, 10, 16, 10))
    original = service.save_rows

    def slow_save(*args, **kwargs):
        clock.advance(minutes=5)   # 大きなファイルの保存に5分かかった
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "save_rows", slow_save)
    log = run_import(db, "pos", "pos.csv", POS_CSV, dept(db, "VEG"), None, lambda: clock.value)
    assert log.finished_at == jst(2026, 10, 16, 10, 5)


@pytest.mark.db
@pytest.mark.parametrize("kind,department,key2", [("pos", "VEG", None), ("products", None, 0)])
def test_import_holds_lock_per_department(db, product_factory, kind, department, key2):
    """同じ部門の取込(商品マスタは商品マスタどうし)は、トランザクションの終わりまで順番待ちにする。"""
    product_factory(code="VEG-001")
    d = dept(db, department) if department else None
    data = POS_CSV if kind == "pos" else (PRODUCTS_HEADER + "VEG-001,キャベツ,VEG,1,1,1\n").encode()
    run_import(db, kind, "a.csv", data, d, None, lambda: jst(2026, 10, 16, 10))
    held = db.execute(text(
        "SELECT classid::bigint, objid::bigint FROM pg_locks "
        "WHERE locktype = 'advisory' AND objsubid = 2 AND pid = pg_backend_pid()")).all()
    assert (IMPORT_LOCK_KEY, d.id if d else key2) in held


@pytest.mark.db
def test_moving_product_expires_open_proposals_of_old_department(db, product_factory, proposal_factory):
    """部門を移した商品は、旧部門の未承認・承認済みの提案を期限切れにする(確定済みは変えない)。"""
    p = product_factory(code="VEG-001")
    other = product_factory(code="VEG-002")
    pending = proposal_factory(p, target=jst(2026, 10, 17).date())
    approved = proposal_factory(p, target=jst(2026, 10, 18).date(), status="approved")
    confirmed = proposal_factory(p, target=jst(2026, 10, 16).date(), status="confirmed")
    untouched = proposal_factory(other)
    now = jst(2026, 10, 16, 10)
    data = (PRODUCTS_HEADER + "VEG-001,キャベツ,FISH,1,1,1\nVEG-002,トマト,VEG,1,1,1\n").encode()
    run_import(db, "products", "products.csv", data, None, None, lambda: now)
    db.expire_all()
    assert db.get(Product, p.id).department_id == dept(db, "FISH").id
    assert [db.get(Proposal, x.id).status for x in (pending, approved, confirmed, untouched)] == [
        "expired", "expired", "confirmed", "pending"]
    histories = db.execute(select(ProposalHistory.proposal_id, ProposalHistory.actor_id, ProposalHistory.occurred_at)
                           .where(ProposalHistory.action == "expire")).all()
    assert sorted(histories) == sorted([(pending.id, None, now), (approved.id, None, now)])


@pytest.mark.db
def test_reimporting_same_department_expires_nothing(db, product_factory, proposal_factory):
    p = product_factory(code="VEG-001")
    pr = proposal_factory(p)
    run_import(db, "products", "products.csv", (PRODUCTS_HEADER + "VEG-001,キャベツ,VEG,6,1,1\n").encode(), None, None,
               lambda: jst(2026, 10, 16, 10))
    db.expire_all()
    assert db.get(Proposal, pr.id).status == "pending"
    assert db.scalar(select(func.count()).select_from(ProposalHistory).where(ProposalHistory.action == "expire")) == 0
    assert db.scalar(select(ImportLog.finished_at)) == jst(2026, 10, 16, 10)
