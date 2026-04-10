from __future__ import annotations

from infra.core.errors import AppError, ErrorCode


def inventory_not_found(product_id: str) -> AppError:
    return AppError(
        code=ErrorCode.PRODUCT_NOT_FOUND,
        message="Inventory item does not exist.",
        status_code=404,
        details={"product_id": product_id},
    )


def inventory_shortage(product_id: str, required_qty: int, available_qty: int) -> AppError:
    return AppError(
        code=ErrorCode.INVENTORY_SHORTAGE,
        message="Insufficient inventory for one or more items.",
        status_code=409,
        details={
            "product_id": product_id,
            "required_qty": required_qty,
            "available_qty": available_qty,
        },
    )
