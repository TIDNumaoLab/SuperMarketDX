"""ログインの照合と、ログイン中の利用者の読み込み。"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from smdx_api.auth.passwords import hash_password, verify_password
from smdx_api.auth.permissions import Principal
from smdx_api.db.models import User

# 存在しない利用者でも照合と同じ時間をかけ、応答時間から利用者の有無を推測させない
_DUMMY_HASH = hash_password("dummy-password-for-timing")


@dataclass(frozen=True)
class LoginLimit:
    """ログインの連続失敗でのロック(環境変数 LOGIN_MAX_FAILURES・LOGIN_LOCK_MINUTES)。"""

    max_failures: int
    lock_minutes: float


def authenticate(db: Session, login_id: str, password: str, now: datetime, limit: LoginLimit) -> User | None:
    """無効な利用者・存在しない利用者・パスワード不一致・ロック中はすべて None(応答から区別させない)。

    存在する利用者の失敗は回数を数え、limit.max_failures 回続いたらロックの期限を付けて回数を0に戻す。
    ロック中は正しいパスワードでも失敗とし、回数も数えない。成功すると回数を0に戻す。
    行をロックしてから数えるので、同時に失敗しても数え漏れない。変更の確定は呼び出し側が行う。
    """
    user = db.scalar(select(User).where(User.login_id == login_id).with_for_update())
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    ok = verify_password(user.password_hash, password)
    if user.locked_until is not None and now < user.locked_until:
        return None
    if not ok:
        user.failed_login_count += 1
        if user.failed_login_count >= limit.max_failures:
            user.locked_until = now + timedelta(minutes=limit.lock_minutes)
            user.failed_login_count = 0
        return None
    user.failed_login_count, user.locked_until = 0, None
    if not user.is_active:
        return None
    return user


def load_principal(db: Session, user_id: int) -> Principal | None:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return Principal(
        user_id=user.id,
        name=user.name,
        role=user.role,
        department_codes=frozenset(d.code for d in user.departments),
    )
