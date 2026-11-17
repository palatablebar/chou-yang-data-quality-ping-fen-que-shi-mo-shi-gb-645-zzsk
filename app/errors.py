"""业务异常 → HTTP 映射。业务代码只抛这些，不直接构造 HTTPException。"""
from __future__ import annotations


class QualiscoreError(Exception):
    status_code = 400
    code = "E_UNKNOWN"

    def __init__(self, message: str, *, code: str | None = None,
                 detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        if code:
            self.code = code

    def payload(self) -> dict:
        return {"error": self.code, "message": self.message, "detail": self.detail}


class BadRequest(QualiscoreError):
    status_code = 400
    code = "E_BAD_REQUEST"


class NotFound(QualiscoreError):
    status_code = 404
    code = "E_NOT_FOUND"


class Conflict(QualiscoreError):
    status_code = 409
    code = "E_CONFLICT"


class UnprocessableInput(QualiscoreError):
    """文件级失败：空文件 / 仅表头 / 全空行 / 表头缺列 / 编码不可解。"""

    status_code = 422
    code = "E_INPUT"


def install_handlers(app) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(QualiscoreError)
    async def _qualiscore(request: Request, exc: QualiscoreError):  # noqa: ANN001
        return JSONResponse(status_code=exc.status_code, content=exc.payload())
