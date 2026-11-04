"""CSV取込(F-01〜F-03)と取込履歴。"""
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from smdx_api.api.deps import FORBIDDEN, current_user, department_for, get_db
from smdx_api.auth.permissions import Principal
from smdx_api.clock import get_clock
from smdx_api.db.models import Department, ImportLog, User
from smdx_api.imports.formats import Kind
from smdx_api.imports.parse import FileFormatError
from smdx_api.imports.service import run_import
from smdx_api.schemas.imports import ImportLogOut
from smdx_api.security import too_large_detail

router = APIRouter(prefix="/api")

HISTORY_LIMIT = 100


def _out(db: Session, log: ImportLog) -> ImportLogOut:
    dept = db.get(Department, log.department_id) if log.department_id else None
    user = db.get(User, log.imported_by) if log.imported_by else None
    return ImportLogOut(
        id=log.id,
        kind=log.kind,
        department_code=dept.code if dept else None,
        file_name=log.file_name,
        imported_count=log.imported_count,
        skipped_count=log.skipped_count,
        errors=log.errors,
        imported_by_name=user.name if user else None,
        finished_at=log.finished_at,
    )


@router.post("/imports/{kind}", response_model=ImportLogOut)
# 同期の関数にして FastAPI のスレッドプールで実行する(DB 処理の間、他の要求を止めない)
def import_csv(
    request: Request,
    kind: Kind,
    file: UploadFile = File(...),
    department_code: str | None = Form(None),
    p: Principal = Depends(current_user),
    db: Session = Depends(get_db),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> ImportLogOut:
    if kind == "products":
        # 商品マスタは店長のみ。部門は行ごとに指定されるため取込先の部門は持たない
        if not p.is_manager:
            raise HTTPException(status_code=403, detail=FORBIDDEN)
        department = None
    else:
        if not department_code:
            raise HTTPException(status_code=422, detail="部門を指定してください")
        department = department_for(department_code, p, db)
    max_mb = request.app.state.config.import_max_mb
    limit = int(max_mb * 1024 * 1024)
    # 上限を1バイト超えた時点で読むのをやめる
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=too_large_detail(max_mb))
    try:
        log = run_import(db, kind, file.filename or "upload.csv", data, department, p.user_id, clock)
    except FileFormatError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=e.message) from None
    db.commit()
    return _out(db, log)


@router.get("/imports", response_model=list[ImportLogOut])
def list_imports(
    kind: Kind | None = None,
    department_code: str | None = None,
    p: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[ImportLogOut]:
    q = select(ImportLog)
    if kind:
        q = q.where(ImportLog.kind == kind)
    if department_code:
        q = q.where(ImportLog.department_id == department_for(department_code, p, db).id)
    elif not p.is_manager:
        # 担当者は自部門の取込と、部門を持たない商品マスタの取込を見られる(詳細設計書「API仕様」)
        own = select(Department.id).where(Department.code.in_(p.department_codes))
        q = q.where(or_(ImportLog.department_id.in_(own), ImportLog.department_id.is_(None)))
    q = q.order_by(ImportLog.finished_at.desc(), ImportLog.id.desc()).limit(HISTORY_LIMIT)
    return [_out(db, log) for log in db.scalars(q)]
