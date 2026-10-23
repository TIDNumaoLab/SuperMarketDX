"""API の共通の依存関係(DBセッション、ログイン利用者、権限チェック)。"""
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.auth.permissions import Principal, can_access_department
from smdx_api.auth.service import load_principal
from smdx_api.db.models import Department
from smdx_api.predictor.registry import ModelRegistry
from smdx_api.weather_client.client import WeatherClient

UNAUTHORIZED = "ログインしてください"
FORBIDDEN = "この操作を行う権限がありません"
NOT_FOUND = "対象が見つかりません"
SESSION_USER_KEY = "user_id"


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_weather_client(request: Request) -> WeatherClient:
    return request.app.state.weather_client


def get_model_registry(request: Request) -> ModelRegistry:
    return request.app.state.model_registry


def current_user(request: Request, db: Session = Depends(get_db)) -> Principal:
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)
    principal = load_principal(db, user_id)
    if principal is None:
        # 利用者が無効化・削除された場合はセッションを捨てる
        request.session.clear()
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)
    return principal


def require_manager(p: Principal = Depends(current_user)) -> Principal:
    if not p.is_manager:
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    return p


def department_for(code: str, p: Principal, db: Session) -> Department:
    """部門コードから部門を引き、操作できるか確かめる(不在は 404、権限なしは 403)。"""
    dept = db.scalar(select(Department).where(Department.code == code))
    if dept is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if not can_access_department(p, dept.code):
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    return dept
