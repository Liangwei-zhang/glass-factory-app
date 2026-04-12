from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InventorySnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: str
    available_qty: int
    reserved_qty: int
    total_qty: int
    safety_stock: int


class InventoryReservationItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class InventoryReservationRequest(BaseModel):
    order_no: str
    items: list[InventoryReservationItem]
    ttl_seconds: int = Field(default=900, ge=60, le=86400)


class InsufficientInventoryItem(BaseModel):
    product_id: str
    required_qty: int
    available_qty: int


class InventoryReservationResult(BaseModel):
    reservation_ids: list[str] = Field(default_factory=list)
    insufficient_items: list[InsufficientInventoryItem] = Field(default_factory=list)
    expires_at: datetime | None = None
