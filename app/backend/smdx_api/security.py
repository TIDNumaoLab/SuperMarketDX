"""CSRF 対策と、取込の要求の大きさの事前確認。

状態を変える API(POST/PUT/PATCH/DELETE)は、画面が付ける独自ヘッダ
`X-Requested-With: smdx` が無い要求を 403 で拒否する。
取込(POST /api/imports/...)は、本文を読む前に Content-Length で大きさを確かめる
(multipart の解析は本文の全体を一時ファイルに書くため、ファイルの上限の確認だけではディスクを守れない)。
"""
from collections.abc import Mapping

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "smdx"
STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FORBIDDEN_DETAIL = "この操作を行う権限がありません"


def is_csrf_safe(method: str, headers: Mapping[str, str]) -> bool:
    if method.upper() not in STATE_CHANGING_METHODS:
        return True
    # ヘッダ名は大文字小文字を区別しない
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get(CSRF_HEADER.lower()) == CSRF_VALUE


class CsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not is_csrf_safe(scope["method"], Headers(scope=scope)):
            response = JSONResponse({"detail": FORBIDDEN_DETAIL}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


IMPORT_PATH_PREFIX = "/api/imports/"
# multipart の境界・見出し・部門などの欄の分。ファイルの上限にこの分を足した大きさまで受け付ける
MULTIPART_OVERHEAD_BYTES = 64 * 1024
LENGTH_REQUIRED_DETAIL = "取込ファイルの大きさが分かりません"


def too_large_detail(max_mb: float) -> str:
    return f"ファイルが大きすぎます(上限 {max_mb:g}MB)。期間を分けて取り込んでください"


class ImportSizeMiddleware:
    """取込の要求の Content-Length が上限を超えれば 413、無ければ 411 で、本文を読まずに拒否する。"""

    def __init__(self, app: ASGIApp, max_mb: float) -> None:
        self.app = app
        self.max_mb = max_mb
        self.limit = int(max_mb * 1024 * 1024) + MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"].startswith(IMPORT_PATH_PREFIX):
            length = Headers(scope=scope).get("content-length")
            response = None
            if length is None or not length.isdigit():
                response = JSONResponse({"detail": LENGTH_REQUIRED_DETAIL}, status_code=411)
            elif int(length) > self.limit:
                response = JSONResponse({"detail": too_large_detail(self.max_mb)}, status_code=413)
            if response is not None:
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
