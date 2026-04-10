from __future__ import annotations

from decimal import Decimal

from infra.core.errors import AppError, ErrorCode


class CustomerCreditExceeded(AppError):
    def __init__(self, customer_id: str, required: Decimal, available: Decimal) -> None:
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message="Customer credit limit exceeded.",
            status_code=422,
            details={
                "customer_id": customer_id,
                "required": str(required),
                "available": str(available),
            },
        )
