from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateShipmentRequest(BaseModel):
    order_id: str
    carrier_name: str | None = Field(default=None, max_length=100)
    tracking_no: str | None = Field(default=None, max_length=100)
    vehicle_no: str | None = Field(default=None, max_length=20)
    driver_name: str | None = Field(default=None, max_length=50)
    driver_phone: str | None = Field(default=None, max_length=20)
    shipped_at: datetime | None = None


class DeliverShipmentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    receiver_name: str = Field(min_length=1, max_length=100)
    receiver_phone: str | None = Field(default=None, max_length=20)
    delivered_at: datetime | None = None
    signature_data_url: str | None = Field(default=None, min_length=10, alias="signatureDataUrl")


class ShipmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_no: str
    order_id: str
    status: str
    carrier_name: str | None = None
    tracking_no: str | None = None
    vehicle_no: str | None = None
    driver_name: str | None = None
    driver_phone: str | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    receiver_name: str | None = None
    receiver_phone: str | None = None
    signature_image: str | None = None
    created_at: datetime
