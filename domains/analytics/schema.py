from __future__ import annotations

from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    orders_today: int = 0
    producing_orders: int = 0
    completed_orders: int = 0
    pending_pickups: int = 0
