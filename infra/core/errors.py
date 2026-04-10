from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from infra.core.context import get_request_context


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    PRODUCT_NOT_FOUND = "PRODUCT_NOT_FOUND"
    INVENTORY_SHORTAGE = "INVENTORY_SHORTAGE"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_INVALID_TRANSITION = "ORDER_INVALID_TRANSITION"


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details or {},
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        context = get_request_context()
        if context is not None:
            payload["request_id"] = context.request_id
        return payload


def register_exception_handlers(app: FastAPI) -> None:
    def resolve_request_id(request: Request) -> str | None:
        context = get_request_context()
        if context is not None:
            return context.request_id
        return getattr(request.state, "request_id", None)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        payload = exc.to_payload()
        request_id = resolve_request_id(request)
        if request_id and "request_id" not in payload:
            payload["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("detail") or "HTTP error")
            details = detail
        elif isinstance(detail, list):
            message = "Request validation failed."
            details = {"detail": detail}
        else:
            message = str(detail)
            details = {}

        if exc.status_code == 401:
            code = ErrorCode.UNAUTHORIZED
        elif exc.status_code == 403:
            code = ErrorCode.FORBIDDEN
        elif exc.status_code >= 500:
            code = ErrorCode.INTERNAL_ERROR
        elif exc.status_code == 400:
            code = ErrorCode.BAD_REQUEST
        else:
            code = ErrorCode.VALIDATION_ERROR

        payload = {
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        request_id = resolve_request_id(_request)
        if request_id is not None:
            payload["request_id"] = request_id

        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        payload = {
            "error": {
                "code": ErrorCode.INTERNAL_ERROR,
                "message": str(exc),
                "details": {},
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        request_id = resolve_request_id(request)
        if request_id is not None:
            payload["request_id"] = request_id
        return JSONResponse(status_code=500, content=payload)
