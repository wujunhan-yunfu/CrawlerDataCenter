"""统一错误响应与异常。"""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class BizError(Exception):
    """业务错误: (http_status, error_code, message)。"""

    def __init__(self, http_status: int, code: str, message: str) -> None:
        self.http_status = http_status
        self.code = code
        self.message = message
        super().__init__(message)


def not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"ok": False, "error": code, "message": message})


def conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail={"ok": False, "error": code, "message": message})


def bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail={"ok": False, "error": code, "message": message})


def forbidden(code: str, message: str = "权限不足") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"ok": False, "error": code, "message": message})


def unauthorized(message: str = "未认证或令牌失效") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"ok": False, "error": "unauthorized", "message": message})


async def biz_error_handler(_: Request, exc: BizError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"ok": False, "error": exc.code, "message": exc.message},
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"ok": False, "error": "invalid_payload", "message": str(exc.errors()[:3])},
    )