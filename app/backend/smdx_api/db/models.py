"""18テーブルの定義。列・型・一意制約は詳細設計書「データ項目定義」に従う。"""
import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from smdx_api.db.base import Base, TimestampMixin

TZDateTime = DateTime(timezone=True)


def _in(column: str, values: tuple[str, ...]) -> str:
    """CHECK 制約の「列が値の一覧のどれか」を作る。"""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (CheckConstraint(_in("business_type", ("order", "production")), name="business_type"),)

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    # order(生鮮の仕入発注)/ production(惣菜の製造計画)。予測単位はこれで決まる
    business_type: Mapped[str] = mapped_column(String(16))


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ("staff", "manager")), name="role"),)

    login_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # 続けてログインに失敗した回数と、ログインできない期限(詳細設計書「API仕様」の POST /api/auth/login)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(TZDateTime)

    departments: Mapped[list[Department]] = relationship(
        secondary="user_departments", order_by="Department.code", viewonly=True
    )


class UserDepartment(TimestampMixin, Base):
    __tablename__ = "user_departments"
    __table_args__ = (UniqueConstraint("user_id", "department_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("order_unit >= 1", name="order_unit"),
        CheckConstraint("lead_time_days >= 0", name="lead_time_days"),
    )

    product_code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    order_unit: Mapped[int] = mapped_column(Integer)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    can_carry_over: Mapped[bool] = mapped_column(Boolean)
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    department: Mapped[Department] = relationship()


class PosSale(TimestampMixin, Base):
    __tablename__ = "pos_sales"
    __table_args__ = (
        # 日計(sales_hour が空)の行も重複させない(PostgreSQL 15 以降)
        UniqueConstraint("sales_date", "sales_hour", "product_id", postgresql_nulls_not_distinct=True),
        CheckConstraint("sales_hour BETWEEN 0 AND 23", name="sales_hour"),
    )

    sales_date: Mapped[dt.date] = mapped_column(Date)
    sales_hour: Mapped[int | None] = mapped_column(Integer)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)


class InventorySnapshot(TimestampMixin, Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint("based_at", "product_id"),
        CheckConstraint(_in("source", ("csv", "manual")), name="source"),
    )

    based_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16))
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DisplayStockEntry(TimestampMixin, Base):
    __tablename__ = "display_stock_entries"
    __table_args__ = (UniqueConstraint("target_date", "entered_at", "product_id"),)

    target_date: Mapped[dt.date] = mapped_column(Date)
    entered_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class WasteRecord(TimestampMixin, Base):
    __tablename__ = "waste_records"
    __table_args__ = (UniqueConstraint("waste_date", "product_id"),)

    waste_date: Mapped[dt.date] = mapped_column(Date)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)


class WeatherForecast(TimestampMixin, Base):
    __tablename__ = "weather_forecasts"
    __table_args__ = (UniqueConstraint("fetched_at", "forecast_time"),)

    fetched_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    forecast_time: Mapped[dt.datetime] = mapped_column(TZDateTime)
    weather_code: Mapped[int] = mapped_column(Integer)
    temperature: Mapped[float] = mapped_column(Float)
    precipitation_probability: Mapped[float | None] = mapped_column(Float)
    precipitation: Mapped[float | None] = mapped_column(Float)


class WeatherActual(TimestampMixin, Base):
    __tablename__ = "weather_actuals"
    __table_args__ = (CheckConstraint(_in("source", ("archive", "historical_forecast")), name="source"),)

    observed_time: Mapped[dt.datetime] = mapped_column(TZDateTime, unique=True)
    weather_code: Mapped[int] = mapped_column(Integer)
    temperature: Mapped[float] = mapped_column(Float)
    precipitation_probability: Mapped[float | None] = mapped_column(Float)
    precipitation: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class CalendarDay(TimestampMixin, Base):
    __tablename__ = "calendar_days"
    __table_args__ = (
        UniqueConstraint("date", "kind"),
        CheckConstraint(_in("kind", ("holiday", "event")), name="kind"),
    )

    date: Mapped[dt.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))


class Promotion(TimestampMixin, Base):
    __tablename__ = "promotions"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Forecast(TimestampMixin, Base):
    __tablename__ = "forecasts"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    target_date: Mapped[dt.date] = mapped_column(Date)
    time_band: Mapped[int | None] = mapped_column(Integer)
    predicted_qty: Mapped[float] = mapped_column(Float)
    # 予測に使ったモデルの版。ベースラインは "baseline"
    model_version: Mapped[str] = mapped_column(String(64))
    features: Mapped[dict[str, Any]] = mapped_column(JSON)
    weather_fetched_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)


PROPOSAL_STATUSES = ("pending", "approved", "confirmed", "expired")
ADJUST_REASONS = ("weather", "promotion", "inventory", "other")


class Proposal(TimestampMixin, Base):
    __tablename__ = "proposals"
    __table_args__ = (
        # 生鮮は time_band が空のため NULL も同一とみなす(PostgreSQL 15 以降)
        UniqueConstraint(
            "department_id", "product_id", "target_date", "time_band", postgresql_nulls_not_distinct=True
        ),
        CheckConstraint(_in("status", PROPOSAL_STATUSES), name="status"),
        CheckConstraint(_in("adjust_reason", ADJUST_REASONS), name="adjust_reason"),
    )

    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    target_date: Mapped[dt.date] = mapped_column(Date)
    time_band: Mapped[int | None] = mapped_column(Integer)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecasts.id"))
    proposed_qty: Mapped[int] = mapped_column(Integer)
    original_qty: Mapped[int] = mapped_column(Integer)
    recalculated_qty: Mapped[int | None] = mapped_column(Integer)
    is_adjusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    adjust_reason: Mapped[str | None] = mapped_column(String(16))
    adjust_note: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    deadline: Mapped[dt.datetime] = mapped_column(TZDateTime)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 最後に予測・計算した日時(修正・承認では変わらない)
    calculated_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    basis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    product: Mapped[Product] = relationship()
    department: Mapped[Department] = relationship()


HISTORY_ACTIONS = ("create", "recalculate", "adjust", "approve", "cancel", "adopt", "confirm", "expire")


class ProposalHistory(TimestampMixin, Base):
    __tablename__ = "proposal_histories"
    __table_args__ = (CheckConstraint(_in("action", HISTORY_ACTIONS), name="action"),)

    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(16))
    # 空はシステムによる操作
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    qty_before: Mapped[int | None] = mapped_column(Integer)
    qty_after: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[dt.datetime] = mapped_column(TZDateTime)


class ProposalJob(TimestampMixin, Base):
    __tablename__ = "proposal_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", ("running", "succeeded", "failed")), name="status"),
        CheckConstraint(_in("scope", ("default", "date")), name="scope"),
    )

    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    # default = 既定表示(target_date は発注日)、date = 対象日の指定(target_date は納品日)
    scope: Mapped[str] = mapped_column(String(16), default="default", server_default="default")
    target_date: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16))
    processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    # 予測の注記(時間帯の設定変更など)。一覧の notice に出す
    notice: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime] = mapped_column(TZDateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime)


class ImportLog(TimestampMixin, Base):
    __tablename__ = "import_logs"
    __table_args__ = (CheckConstraint(_in("kind", ("products", "pos", "inventory", "waste")), name="kind"),)

    kind: Mapped[str] = mapped_column(String(16))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    imported_count: Mapped[int] = mapped_column(Integer)
    skipped_count: Mapped[int] = mapped_column(Integer)
    # [{"row": 行番号, "reason": 理由}]
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # 空は管理コマンドによる取込
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    finished_at: Mapped[dt.datetime] = mapped_column(TZDateTime)


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
