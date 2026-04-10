from __future__ import annotations

from infra.core.errors import AppError, ErrorCode


def order_not_found(order_id: str) -> AppError:
    return AppError(
        code=ErrorCode.ORDER_NOT_FOUND,
        message="Order not found.",
        status_code=404,
        details={"order_id": order_id},
    )
