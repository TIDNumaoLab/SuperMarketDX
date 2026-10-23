"""アプリの生成、ミドルウェア、ルータ登録。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from smdx_api.api import (
    routes_auth,
    routes_calendar,
    routes_imports,
    routes_inventory,
    routes_products,
    routes_promotions,
    routes_settings,
)
from smdx_api.config import AppConfig, get_config
from smdx_api.db.session import make_engine, make_session_factory
from smdx_api.security import CSRF_HEADER, CsrfMiddleware
from smdx_api.predictor.registry import ModelRegistry
from smdx_api.weather_client.client import OpenMeteoClient

SESSION_COOKIE_NAME = "smdx_session"


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()
    app = FastAPI(title="スーパーマーケットDX API")
    app.state.config = config
    # 接続は最初の利用時に張られる(DB が無くても /health は応答する)
    app.state.session_factory = make_session_factory(make_engine(config.database_url))
    # 気象APIの呼び出しは差し替え可能にする(試験では偽のクライアントに置き換える)
    app.state.weather_client = OpenMeteoClient.from_config(config)
    # モデルファイルは起動時に読み込んで適合確認し、使えない場合は理由をログに出す(以後はファイルの更新時に読み直す)
    registry = ModelRegistry({"daily": Path(config.model_daily_path), "time_band": Path(config.model_time_band_path)})
    for granularity in ("daily", "time_band"):
        registry.status(granularity)
    app.state.model_registry = registry

    # add_middleware は後に追加したものほど外側になる。外側から CORS → CSRF → セッション の順にする
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret,
        session_cookie=SESSION_COOKIE_NAME,
        max_age=int(config.session_max_age_hours * 3600),
        same_site="lax",
        https_only=config.session_cookie_secure,
    )
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_auth.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_imports.router)
    app.include_router(routes_inventory.router)
    app.include_router(routes_products.router)
    app.include_router(routes_calendar.router)
    app.include_router(routes_promotions.router)
    return app
