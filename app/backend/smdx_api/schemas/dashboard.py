"""今日の状況 API の出力(詳細設計書「今日の状況(GET /api/dashboard)の項目」)。"""
import datetime as dt

from pydantic import BaseModel

from smdx_api.schemas.common import JstDatetime
from smdx_api.schemas.proposals import JobOut


class LastJobOut(BaseModel):
    status: str
    finished_at: JstDatetime | None
    error: str | None


class DashboardDepartmentOut(BaseModel):
    department_code: str
    department_name: str
    business_type: str
    # この要求で開始した、または実行中のジョブ
    job: JobOut | None
    last_job: LastJobOut | None


class WarningCountOut(BaseModel):
    code: str
    count: int


class DeadlineOut(BaseModel):
    department_code: str
    deadline: JstDatetime
    target_date: dt.date
    time_band: int | None
    pending: int
    approved: int
    confirmed: int
    expired: int
    # 未承認のうち警告が無く一括承認できる件数
    bulk_approvable: int
    # 未承認の提案の警告の種類別件数
    warnings: list[WarningCountOut]


class TomorrowWeatherOut(BaseModel):
    weather_code: int | None
    weather_label: str
    temperature: float | None
    temperature_min: float | None
    precipitation: float | None
    fetched_at: JstDatetime


class TomorrowPromotionOut(BaseModel):
    department_name: str
    product_name: str
    start_date: dt.date
    end_date: dt.date
    description: str


class CalendarEntryOut(BaseModel):
    kind: str
    name: str


class TomorrowOut(BaseModel):
    date: dt.date
    weather: TomorrowWeatherOut | None
    promotions: list[TomorrowPromotionOut]
    calendar: list[CalendarEntryOut]


class DataStatusOut(BaseModel):
    department_code: str
    pos_latest_date: dt.date | None
    pos_imported_at: JstDatetime | None
    inventory_based_at: JstDatetime | None
    stale_pos: bool


class BusinessHoursOut(BaseModel):
    """営業時間(HH:MM)。時間軸の範囲に使う。"""
    open: str
    close: str


class DashboardOut(BaseModel):
    now: JstDatetime
    business_hours: BusinessHoursOut
    departments: list[DashboardDepartmentOut]
    deadlines: list[DeadlineOut]
    tomorrow: TomorrowOut
    data_status: list[DataStatusOut]
