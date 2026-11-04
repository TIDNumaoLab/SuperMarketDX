"""CSV取込の実行と取込履歴の記録。"""
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from smdx_api.db.models import Department, ImportLog, Product
from smdx_api.imports.formats import Kind
from smdx_api.imports.parse import ParseContext, ProductRow, parse_csv
from smdx_api.imports.save import save_rows
from smdx_api.proposals.deadlines import expire_moved_products

# 取込履歴に残すエラー行の上限(件数は skipped_count に全件残る)。部門を間違えたファイルなどで履歴が肥大しないようにする
MAX_STORED_ERRORS = 100
FILE_NAME_MAX = 255
# 取込を順番に行うためのアドバイザリロックの種別(2つ目のキーは部門の ID。商品マスタは 0)
IMPORT_LOCK_KEY = 0x534D4458


def build_context(db: Session, department: Department | None) -> ParseContext:
    products = {
        code: (pid, dept)
        for code, pid, dept in db.execute(
            select(Product.product_code, Product.id, Department.code).join(Department, Product.department_id == Department.id)
        )
    }
    return ParseContext(
        products=products,
        department_code=department.code if department is not None else None,
        known_departments=set(db.scalars(select(Department.code))),
    )


def run_import(
    db: Session,
    kind: Kind,
    file_name: str,
    data: bytes,
    department: Department | None,
    user_id: int | None,
    clock: Callable[[], datetime],
) -> ImportLog:
    """CSV を検証して保存し、取込履歴を残す。ファイル全体が読めなければ FileFormatError(履歴は残さない)。

    imported_count はファイルの有効な行数、skipped_count はスキップした行数。エラー行は先頭の MAX_STORED_ERRORS 件だけ残す。
    同じ部門の取込(商品マスタは商品マスタどうし)は、トランザクションの終わりまで順番待ちにする
    (同じ日付×商品の POS を同時に取り込むと、削除してから挿入する間に一意制約で衝突するため)。
    終了日時は保存し終えた時刻とする(取込中に始まった再計算が、取込前のデータの提案を最新と判定しないように)。
    """
    db.execute(select(func.pg_advisory_xact_lock(IMPORT_LOCK_KEY, department.id if department is not None else 0)))
    result = parse_csv(kind, data, build_context(db, department))
    moved = _moving_products(db, result.rows) if kind == "products" else []
    save_rows(db, kind, result.rows)
    if moved:
        expire_moved_products(db, moved, clock())
    log = ImportLog(
        kind=kind,
        department_id=department.id if department is not None else None,
        file_name=file_name[:FILE_NAME_MAX],
        imported_count=len(result.rows),
        skipped_count=len(result.errors),
        errors=[{"row": e.row, "reason": e.reason} for e in result.errors[:MAX_STORED_ERRORS]],
        imported_by=user_id,
        finished_at=clock(),
    )
    db.add(log)
    db.flush()
    return log


def _moving_products(db: Session, rows: list) -> list[int]:
    """商品マスタの取込で部門が変わる既存商品の ID(ファイル内の重複は後の行を使う)。"""
    new_dept = {r.product_code: r.department_code for r in rows if isinstance(r, ProductRow)}
    if not new_dept:
        return []
    current = db.execute(
        select(Product.id, Product.product_code, Department.code)
        .join(Department, Product.department_id == Department.id)
        .where(Product.product_code.in_(new_dept))
    )
    return [pid for pid, code, dept in current if new_dept[code] != dept]
