from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateOrderItem(BaseModel):
    product_id: str
    product_name: str
    glass_type: str
    specification: str
    width_mm: int = Field(gt=0)
    height_mm: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(gt=Decimal("0"))
    process_requirements: str = ""


class CreateOrderRequest(BaseModel):
    customer_id: str
    delivery_address: str
    expected_delivery_date: datetime
    items: list[CreateOrderItem]
    priority: str = "normal"
    remark: str = ""
    idempotency_key: str | None = None


class UpdateOrderItemRequest(BaseModel):
    id: str
    glass_type: str | None = None
    specification: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    process_requirements: str | None = None


class UpdateOrderRequest(BaseModel):
    delivery_address: str | None = None
    expected_delivery_date: datetime | None = None
    priority: str | None = None
    remark: str | None = None
    items: list[UpdateOrderItemRequest] = Field(default_factory=list)


class CancelOrderRequest(BaseModel):
    reason: str = ""


class PickupSignatureRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    signer_name: str = Field(min_length=1, max_length=100, alias="signerName")
    signature_data_url: str = Field(min_length=10, alias="signatureDataUrl")


class StepActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: str
    piece_numbers: list[int] = Field(default_factory=list, alias="pieceNumbers")
    note: str = ""


class OrderItemView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    product_name: str
    glass_type: str
    specification: str
    width_mm: int
    height_mm: int
    area_sqm: Decimal
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    process_requirements: str


class OrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_no: str
    customer_id: str
    status: str
    priority: str
    total_amount: Decimal
    total_quantity: int
    total_area_sqm: Decimal
    delivery_address: str
    expected_delivery_date: datetime
    pickup_approved_at: datetime | None = None
    pickup_approved_by: str | None = None
    picked_up_at: datetime | None = None
    picked_up_by: str | None = None
    pickup_signer_name: str | None = None
    pickup_signature_key: str | None = None
    drawing_object_key: str | None = None
    drawing_original_name: str | None = None
    reservation_ids: list[str]
    remark: str
    version: int
    created_at: datetime
    items: list[OrderItemView] = Field(default_factory=list)


class OrderTimelineEvent(BaseModel):
    event: str
    created_at: datetime
    status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
