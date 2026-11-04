"""検証済みの行の保存。

再取込時の上書き単位(詳細設計書「標準取込形式」):
- 商品マスタ: 商品コードで更新または追加(ファイルに無い既存商品は変更しない)
- POS: 「日付×商品」の既存行(すべての時刻)を削除してから、「日付×時×商品」で合計して挿入
- 廃棄: 「日付×商品」で合計して更新または追加
- 在庫: 「基準日時×商品」で更新または追加(ファイル内の重複は後の行を採用)
"""
from collections.abc import Sequence

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from smdx_api.db.models import Department, InventorySnapshot, PosSale, Product, WasteRecord
from smdx_api.imports.formats import Kind
from smdx_api.imports.parse import InventoryRow, PosRow, ProductRow, Row, WasteRow

_CHUNK = 1000


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _save_products(db: Session, rows: Sequence[ProductRow]) -> int:
    dept_ids = {d.code: d.id for d in db.scalars(select(Department))}
    existing = {p.product_code: p for p in db.scalars(select(Product).where(Product.product_code.in_([r.product_code for r in rows])))}
    latest = {r.product_code: r for r in rows}
    for code, r in latest.items():
        values = dict(
            name=r.name,
            department_id=dept_ids[r.department_code],
            order_unit=r.order_unit,
            lead_time_days=r.lead_time_days,
            can_carry_over=r.can_carry_over,
            cost_price=r.cost_price,
            selling_price=r.selling_price,
            is_active=True,
        )
        p = existing.get(code)
        if p is None:
            db.add(Product(product_code=code, **values))
        else:
            for k, v in values.items():
                setattr(p, k, v)
    db.flush()
    return len(latest)


def _save_pos(db: Session, rows: Sequence[PosRow]) -> int:
    totals: dict[tuple, int] = {}
    for r in rows:
        key = (r.sales_date, r.sales_hour, r.product_id)
        totals[key] = totals.get(key, 0) + r.quantity
    pairs = sorted({(d, p) for d, _, p in totals})
    for chunk in _chunks(pairs):
        db.execute(delete(PosSale).where(tuple_(PosSale.sales_date, PosSale.product_id).in_(chunk)))
    values = [dict(sales_date=d, sales_hour=h, product_id=p, quantity=q) for (d, h, p), q in totals.items()]
    for chunk in _chunks(values):
        db.execute(insert(PosSale), chunk)
    return len(values)


def _save_waste(db: Session, rows: Sequence[WasteRow]) -> int:
    totals: dict[tuple, int] = {}
    for r in rows:
        key = (r.waste_date, r.product_id)
        totals[key] = totals.get(key, 0) + r.quantity
    values = [dict(waste_date=d, product_id=p, quantity=q) for (d, p), q in totals.items()]
    for chunk in _chunks(values):
        stmt = insert(WasteRecord).values(chunk)
        db.execute(stmt.on_conflict_do_update(
            index_elements=["waste_date", "product_id"],
            set_={"quantity": stmt.excluded.quantity, "updated_at": stmt.excluded.updated_at},
        ))
    return len(values)


def _save_inventory(db: Session, rows: Sequence[InventoryRow], source: str = "csv", entered_by: int | None = None) -> int:
    latest: dict[tuple, int] = {}
    for r in rows:
        latest[(r.based_at, r.product_id)] = r.quantity
    # 更新日時は文の実行時刻にする(now() はトランザクションの開始時刻のため、保存より前の時刻になる。最新性判定で使う)
    values = [dict(based_at=t, product_id=p, quantity=q, source=source, entered_by=entered_by, updated_at=func.clock_timestamp())
              for (t, p), q in latest.items()]
    for chunk in _chunks(values):
        stmt = insert(InventorySnapshot).values(chunk)
        db.execute(stmt.on_conflict_do_update(
            index_elements=["based_at", "product_id"],
            set_={
                "quantity": stmt.excluded.quantity,
                "source": stmt.excluded.source,
                "entered_by": stmt.excluded.entered_by,
                "updated_at": stmt.excluded.updated_at,
            },
        ))
    return len(values)


def save_rows(db: Session, kind: Kind, rows: Sequence[Row]) -> int:
    """保存した件数(ファイル内の重複をまとめた後の件数)を返す。"""
    if not rows:
        return 0
    if kind == "products":
        return _save_products(db, rows)
    if kind == "pos":
        return _save_pos(db, rows)
    if kind == "waste":
        return _save_waste(db, rows)
    return _save_inventory(db, rows)


def save_inventory(db: Session, rows: Sequence[InventoryRow], source: str, entered_by: int | None) -> int:
    """在庫の保存(CSV取込と手入力で共用)。"""
    return _save_inventory(db, rows, source, entered_by) if rows else 0
