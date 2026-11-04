"""ログイン・ログアウト・ログイン中の利用者。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.api.deps import SESSION_USER_KEY, current_user, get_db
from smdx_api.auth.permissions import Principal
from smdx_api.auth.service import LoginLimit, authenticate
from smdx_api.clock import get_now
from smdx_api.db.models import Department, User
from smdx_api.schemas.auth import DepartmentRef, LoginRequest, MeResponse

router = APIRouter(prefix="/api")

LOGIN_FAILED = "ログインIDまたはパスワードが正しくありません。"


def _ref(d: Department) -> DepartmentRef:
    return DepartmentRef(code=d.code, name=d.name, business_type=d.business_type)


def _me(db: Session, user: User) -> MeResponse:
    own = sorted(user.departments, key=lambda d: d.code)
    if user.role == "manager":
        accessible = list(db.scalars(select(Department).order_by(Department.code)))
    else:
        accessible = own
    return MeResponse(
        user_id=user.id,
        name=user.name,
        role=user.role,
        departments=[_ref(d) for d in own],
        accessible_departments=[_ref(d) for d in accessible],
    )


@router.post("/auth/login", response_model=MeResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db),
          now: datetime = Depends(get_now)) -> MeResponse:
    config = request.app.state.config
    user = authenticate(db, body.login_id, body.password, now,
                        LoginLimit(config.login_max_failures, config.login_lock_minutes))
    # 失敗の回数・ロックの期限は、ログインに失敗しても残す
    db.commit()
    if user is None:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return _me(db, user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, _: Principal = Depends(current_user)) -> Response:
    request.session.clear()
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
def me(p: Principal = Depends(current_user), db: Session = Depends(get_db)) -> MeResponse:
    return _me(db, db.get(User, p.user_id))
