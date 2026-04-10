from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    order_id: str | None = None
    title: str
    message: str
    severity: str
    is_read: bool
    created_at: datetime


class MarkNotificationsReadRequest(BaseModel):
    notification_ids: list[str] = Field(default_factory=list)


class MarkNotificationsReadResult(BaseModel):
    updated_count: int
