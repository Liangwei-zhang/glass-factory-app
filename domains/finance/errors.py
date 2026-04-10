from infra.core.errors import AppError, ErrorCode


class ReceivableNotFound(AppError):
    def __init__(self, receivable_id: str) -> None:
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message="Receivable not found.",
            status_code=404,
            details={"receivable_id": receivable_id},
        )
