"""在庫の手入力(F-03)と惣菜の陳列残数の入力(F-08)。"""
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from smdx_api.db.models import Department, DisplayStockEntry, Product
from smdx_api.imports.parse import InventoryRow
from smdx_api.imports.save import save_inventory


class ManualInputError(Exception):
    def __init__(self, product_code: str, reason: str) -> None:
        super().__init__(reason)
        self.product_code = product_code
        self.reason = reason


def _product_ids(db: Session, department: Department, codes: Sequence[str]) -> dict[str, int]:
    """商品コード → product_id。未登録・部門外の商品が1件でもあれば ManualInputError。"""
    found = {p.product_code: p for p in db.scalars(select(Product).where(Product.product_code.in_(codes)))}
    for code in codes:
        p = found.get(code)
        if p is None:
            raise ManualInputError(code, f"未登録の商品コードです: {code}")
        if p.department_id != department.id:
            raise ManualInputError(code, f"この部門の商品ではありません: {code}")
    return {code: found[code].id for code in codes}


def save_manual_inventory(
    db: Session, department: Department, based_at: datetime, items: Sequence[tuple[str, int]], user_id: int
) -> int:
    ids = _product_ids(db, department, [code for code, _ in items])
    rows = [InventoryRow(based_at, ids[code], qty) for code, qty in items]
    return save_inventory(db, rows, source="manual", entered_by=user_id)


def save_display_stock(
    db: Session, department: Department, target: date, entered_at: datetime, items: Sequence[tuple[str, int]],
    user_id: int | None,
) -> int:
    """陳列残数を (対象日, 入力時刻, 商品) で上書き保存する。同じ商品が重なれば後のものを使う。保存した件数を返す。"""
    ids = _product_ids(db, department, [code for code, _ in items])
    latest = {ids[code]: qty for code, qty in items}
    if not latest:
        return 0
    stmt = insert(DisplayStockEntry).values([
        # 更新日時は文の実行時刻にする(最新性判定で使う。now() はトランザクションの開始時刻になる)
        dict(target_date=target, entered_at=entered_at, product_id=pid, quantity=qty, entered_by=user_id,
             updated_at=func.clock_timestamp())
        for pid, qty in latest.items()
    ])
    db.execute(stmt.on_conflict_do_update(
        index_elements=["target_date", "entered_at", "product_id"],
        # 最新性判定は行の更新日時で入れ直しを検出する
        set_={"quantity": stmt.excluded.quantity, "entered_by": stmt.excluded.entered_by,
              "updated_at": stmt.excluded.updated_at},
    ))
    return len(latest)
