"""本体の試験で共通に使う fixture。

DB を使う試験は `@pytest.mark.db` を付け、環境変数 TEST_DATABASE_URL があるときだけ実行する。
試験用DBは public スキーマを作り直してから `alembic upgrade head` で作る(create_all は使わない)。
DB 名が `_test` で終わらなければ、DB に触れずに試験を止める。
"""
import itertools
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import make_url, select, text
from sqlalchemy.orm import Session

from smdx_api.api.deps import get_db
from smdx_api.config import AppConfig
from smdx_api.auth.passwords import hash_password
from smdx_api.clock import JST, get_clock, get_now
from smdx_api.db.models import (
    Department,
    DisplayStockEntry,
    Forecast,
    InventorySnapshot,
    PosSale,
    Product,
    Proposal,
    User,
    UserDepartment,
)
from smdx_api.db.session import make_engine
from smdx_api.main import create_app

TEST_SESSION_SECRET = "test-secret-" + "x" * 32
BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(monkeypatch) -> AppConfig:
    """試験用の設定。.env は読まず、SESSION_SECRET だけを与える。"""
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    return AppConfig(_env_file=None)


@pytest.fixture(scope="session")
def db_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL が未設定のため DB 試験をスキップ")
    # public スキーマを作り直すので、開発用の DB を誤って指定しても消さないよう、名前が _test で終わる DB に限る
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        pytest.exit(f"TEST_DATABASE_URL の DB 名は _test で終わるものにしてください(指定: {name})", returncode=4)
    # 本体と同じ接続設定(タイムゾーン Asia/Tokyo)にする
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """試験ごとのセッション。試験後にロールバックし、DB を元に戻す。"""
    conn = db_engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    trans.rollback()
    conn.close()


class FixedClock:
    """試験用の時計。API の現在時刻(get_now)をこの値に固定する。"""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def set(self, value: datetime) -> None:
        self.value = value

    def advance(self, **delta) -> None:
        self.value = self.value + timedelta(**delta)


@pytest.fixture
def fixed_now() -> FixedClock:
    return FixedClock(datetime(2026, 10, 16, 10, 0, tzinfo=JST))


def _apply_overrides(request, app) -> None:
    if "db" in request.fixturenames:
        session = request.getfixturevalue("db")
        app.dependency_overrides[get_db] = lambda: session
    if "fixed_now" in request.fixturenames:
        clock = request.getfixturevalue("fixed_now")
        app.dependency_overrides[get_now] = lambda: clock.value
        app.dependency_overrides[get_clock] = lambda: (lambda: clock.value)


@pytest.fixture
def app(request, config):
    app = create_app(config)
    _apply_overrides(request, app)
    return app


@pytest.fixture
def client(app):
    """状態を変える API を通すため、既定で CSRF 用ヘッダを付けたクライアント。"""
    return TestClient(app, headers={"X-Requested-With": "smdx"})


@pytest.fixture
def make_client(request, config):
    """設定の一部を上書きしたアプリのクライアントを作る(db を使う試験では同じセッションを共有する)。"""

    def make(**overrides) -> TestClient:
        app = create_app(config.model_copy(update=overrides))
        _apply_overrides(request, app)
        return TestClient(app, headers={"X-Requested-With": "smdx"})

    return make


_login_ids = itertools.count(1)


@pytest.fixture
def user_factory(db):
    """利用者を1件作る。パスワードの既定は pass1234。"""

    def make(
        login_id: str | None = None,
        name: str = "試験 太郎",
        role: str = "staff",
        departments: tuple[str, ...] = ("VEG",),
        password: str = "pass1234",
        is_active: bool = True,
    ) -> User:
        u = User(
            login_id=login_id or f"user{next(_login_ids)}",
            name=name,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        db.add(u)
        db.flush()
        for code in departments:
            dept = db.scalar(select(Department).where(Department.code == code))
            db.add(UserDepartment(user_id=u.id, department_id=dept.id))
        db.flush()
        db.expire(u, ["departments"])
        return u

    return make


@pytest.fixture
def login():
    """画面と同じ API でログインする。"""

    def do(client: TestClient, user: User, password: str = "pass1234"):
        res = client.post("/api/auth/login", json={"login_id": user.login_id, "password": password})
        assert res.status_code == 200, res.text
        return res

    return do


_codes = itertools.count(1)


@pytest.fixture
def product_factory(db):
    """商品を1件作る。既定は部門 VEG・入数1・リードタイム1日・持越可。"""

    def make(code: str | None = None, department: str = "VEG", is_active: bool = True, **fields) -> Product:
        dept = db.scalar(select(Department).where(Department.code == department))
        values = dict(
            product_code=code or f"{department}-T{next(_codes):03d}",
            name=fields.pop("name", "試験用商品"),
            department_id=dept.id,
            order_unit=1,
            lead_time_days=0 if dept.business_type == "production" else 1,
            can_carry_over=dept.business_type == "order",
            is_active=is_active,
        )
        values.update(fields)
        p = Product(**values)
        db.add(p)
        db.flush()
        return p

    return make


def jst(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=JST)


@pytest.fixture
def add_inventory(db):
    """在庫を1件登録する(段階5でも使う)。"""

    def add(product: Product, based_at: datetime, quantity: int, source: str = "csv") -> InventorySnapshot:
        row = InventorySnapshot(based_at=based_at, product_id=product.id, quantity=quantity, source=source)
        db.add(row)
        db.flush()
        return row

    return add


@pytest.fixture
def add_pos(db):
    """POS を登録する。hour=None は日計。"""

    def add(product: Product, day: date, quantity: int, hour: int | None = None) -> None:
        db.add(PosSale(sales_date=day, sales_hour=hour, product_id=product.id, quantity=quantity))
        db.flush()

    return add


@pytest.fixture
def proposal_factory(db, product_factory):
    """提案を1件作る(元になる予測結果も作る)。product を省略すると VEG の商品を作る。"""

    def make(
        product: Product | None = None,
        *,
        product_code: str | None = None,
        product_offset: int | None = None,
        target: date = date(2026, 10, 17),
        time_band: int | None = None,
        qty: int = 10,
        status: str = "pending",
        deadline: datetime = jst(2026, 10, 16, 20),
        warnings: list[str] | None = None,
        is_adjusted: bool = False,
        recalculated_qty: int | None = None,
        calculated_at: datetime | None = None,
        basis: dict | None = None,
        approved_by: int | None = None,
    ) -> Proposal:
        if product is None:
            code = product_code or (f"VEG-P{product_offset:03d}" if product_offset is not None else None)
            product = product_factory(code=code)
        calculated_at = calculated_at or jst(2026, 10, 16, 9)
        f = Forecast(product_id=product.id, target_date=target, time_band=time_band, predicted_qty=float(qty),
                     model_version="baseline", features={}, weather_fetched_at=calculated_at)
        db.add(f)
        db.flush()
        p = Proposal(
            department_id=product.department_id, product_id=product.id, target_date=target, time_band=time_band,
            forecast_id=f.id, proposed_qty=qty, original_qty=qty, recalculated_qty=recalculated_qty,
            is_adjusted=is_adjusted, status=status, deadline=deadline, warnings=list(warnings or []),
            calculated_at=calculated_at, approved_by=approved_by,
            approved_at=calculated_at if status in ("approved", "confirmed") else None,
            basis=basis if basis is not None else {"model_version": "baseline", "weather_fetched_at": calculated_at.isoformat()},
        )
        db.add(p)
        db.flush()
        return p

    return make


def dept(db: Session, code: str) -> Department:
    return db.scalar(select(Department).where(Department.code == code))


def one(items, product_code: str):
    """計算結果から商品コードの1件を取り出す。"""
    found = [c for c in items if c.product_code == product_code]
    assert len(found) == 1, f"{product_code}: {len(found)}件"
    return found[0]


@pytest.fixture
def veg_setup(db, product_factory, add_pos, add_inventory, fixed_now) -> Product:
    """VEG-001(入数6・LT1・持越可)。POS は 10/02〜10/15 の日計が毎日10、10/10(土)だけ20。
    在庫は 10/16 14:30 に 8。現在は 10/16 15:00(締め 20:00 より前)。"""
    fixed_now.set(jst(2026, 10, 16, 15))
    p = product_factory(code="VEG-001", order_unit=6, lead_time_days=1, can_carry_over=True)
    for i in range(14):
        d = date(2026, 10, 2) + timedelta(days=i)
        add_pos(p, d, 20 if d == date(2026, 10, 10) else 10)
    add_inventory(p, jst(2026, 10, 16, 14, 30), 8)
    return p


@pytest.fixture
def add_display_stock(db):
    """惣菜の陳列残数を1件登録する。"""

    def add(product: Product, target: date, entered_at: datetime, qty: int) -> DisplayStockEntry:
        row = DisplayStockEntry(target_date=target, entered_at=entered_at, product_id=product.id, quantity=qty)
        db.add(row)
        db.flush()
        return row

    return add


# 時間帯の時(開始)ごとの1日の販売数: 10時帯 1、11時帯 6、14時帯 3、17時帯 9
DELI_HOURLY = {10: 1, 11: 2, 12: 2, 13: 2, 14: 1, 15: 1, 16: 1, 17: 3, 18: 3, 19: 3}


@pytest.fixture
def deli_setup(db, product_factory, add_pos, fixed_now) -> Product:
    """DELI-001(唐揚げ)。10/02〜10/15 の時刻つき POS は毎日 DELI_HOURLY。現在は 10/16 8:00(最初の製造開始 9:00 より前)。"""
    fixed_now.set(jst(2026, 10, 16, 8))
    p = product_factory(code="DELI-001", department="DELI", name="唐揚げ")
    for i in range(14):
        d = date(2026, 10, 2) + timedelta(days=i)
        for hour, q in DELI_HOURLY.items():
            add_pos(p, d, q, hour)
    return p


@pytest.fixture
def baseline_services(tmp_path):
    """モデルなし(ベースライン)・偽の気象クライアント。"""
    from smdx_api.proposals.compute_fresh import ComputeServices
    from tests.fake_models import empty_registry
    from tests.fakes import FakeWeatherClient

    return ComputeServices(empty_registry(tmp_path), FakeWeatherClient())


@pytest.fixture
def model_services(tmp_path):
    """常に5を返すモデル・偽の気象クライアント。"""
    from smdx_api.proposals.compute_fresh import ComputeServices
    from tests.fake_models import const_registry
    from tests.fakes import FakeWeatherClient

    return ComputeServices(const_registry(tmp_path), FakeWeatherClient())


@pytest.fixture
def job_session_factory(db):
    """ジョブ(run_job)が使うセッション工場。試験の db と同じ接続・トランザクションの中のセーブポイントで動く。
    1つの接続を共用するため、並行して実行するジョブ(今日の状況)は with の間ロックを持ち、1つずつ順に動かす。"""
    import threading

    conn = db.connection()
    # 同じスレッドの中で入れ子にセッションを開く試験(test_jobs)があるので、再入できるロックにする
    lock = threading.RLock()

    class SerialSession(Session):
        def __enter__(self):
            lock.acquire()
            return super().__enter__()

        def __exit__(self, *exc):
            try:
                return super().__exit__(*exc)
            finally:
                lock.release()

    def make() -> Session:
        return SerialSession(bind=conn, join_transaction_mode="create_savepoint")

    return make


@pytest.fixture
def test_services(app, baseline_services, job_session_factory):
    """提案のAPIの試験用: 計算はベースライン・偽の気象、ジョブは試験の DB の中で動かす。"""
    from smdx_api.api.deps import get_compute_services, get_session_factory

    app.dependency_overrides[get_compute_services] = lambda: baseline_services
    app.dependency_overrides[get_session_factory] = lambda: job_session_factory
    return baseline_services
