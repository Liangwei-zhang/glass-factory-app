from infra.core.errors import AppError, ErrorCode


class ShipmentNotFound(AppError):
    def __init__(self, shipment_id: str) -> None:
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message="Shipment not found.",
            status_code=404,
            details={"shipment_id": shipment_id},
        )
