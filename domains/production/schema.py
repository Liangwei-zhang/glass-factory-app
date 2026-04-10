from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class WorkOrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_no: str
    order_id: str
    process_step_key: str
    assigned_user_id: str | None = None
    rework_unread: bool = False
    status: str
    glass_type: str
    specification: str
    quantity: int
    completed_qty: int
    defect_qty: int
    scheduled_date: date | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ProductionLineView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    line_code: str
    line_name: str
    supported_glass_types: list[str]
    max_width_mm: int
    max_height_mm: int
    supported_processes: list[str]
    is_active: bool
