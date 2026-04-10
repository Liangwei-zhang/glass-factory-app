from __future__ import annotations

from infra.core.errors import AppError, ErrorCode


class ProductionScheduleError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            status_code=422,
        )
