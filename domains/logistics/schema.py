from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ShipmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_no: str
    order_id: str
    status: str
    carrier_name: str | None = None
    tracking_no: str | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
