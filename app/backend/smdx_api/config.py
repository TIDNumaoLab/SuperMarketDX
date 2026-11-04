"""環境変数からの設定読込(詳細設計書「設定項目」の環境変数)。"""
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from smdx_api.db.url import DEFAULT_DATABASE_URL
from smdx_api.weather_client.config import (
    DEFAULT_ARCHIVE_URL,
    DEFAULT_FORECAST_URL,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TIMEOUT_SECONDS,
)


class AppConfig(BaseSettings):
    # model_daily_path などの項目名が pydantic の予約名(model_)と重ならないようにする
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", protected_namespaces=("settings_",)
    )

    database_url: str = DEFAULT_DATABASE_URL
    weather_api_base_url: str = DEFAULT_FORECAST_URL
    weather_api_archive_url: str = DEFAULT_ARCHIVE_URL
    weather_api_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    store_latitude: float = DEFAULT_LATITUDE
    store_longitude: float = DEFAULT_LONGITUDE
    model_daily_path: str = "models/daily.joblib"
    model_time_band_path: str = "models/time_band.joblib"
    # カンマ区切りの文字列で受け、リストに分割する。
    # str との共用型にすると、JSON として読めない値でもエラーにせず検証関数へ渡される
    cors_allow_origins: list[str] | str = ["http://localhost:5173"]
    # 必須。空や短い鍵ではセッションCookieを偽造できるため、32文字以上を求める
    session_secret: str = Field(min_length=32)
    session_cookie_secure: bool = False
    # 最後の操作からこの時間でログアウトになる(SessionMiddleware が応答ごとに Cookie を出し直す)
    session_max_age_hours: float = Field(default=3, gt=0)
    # 取込ファイルの上限(MB)。全体をメモリに読んで検証するため、大きすぎるファイルで本体が止まらないようにする
    import_max_mb: float = Field(default=50, gt=0)
    # 同じログインIDでこの回数続けて失敗すると、LOGIN_LOCK_MINUTES の間ログインできなくする(パスワードの総当たり対策)
    login_max_failures: int = Field(default=5, ge=1)
    login_lock_minutes: float = Field(default=15, gt=0)
    # /docs・/redoc・/openapi.json を出すか(インターネットから届く評価環境では false)
    api_docs_enabled: bool = True

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
