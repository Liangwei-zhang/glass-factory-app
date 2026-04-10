from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infra.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProductionLineModel(Base):
    __tablename__ = "production_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    line_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    line_name: Mapped[str] = mapped_column(String(100))
    supported_glass_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    max_width_mm: Mapped[int] = mapped_column(Integer, default=3000)
    max_height_mm: Mapped[int] = mapped_column(Integer, default=6000)
    daily_capacity_sqm: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    supported_processes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkOrderModel(Base):
    __tablename__ = "work_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    work_order_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    order_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("order_items.id"), index=True)
    production_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("production_lines.id"), nullable=True, index=True
    )
    assigned_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    process_step_key: Mapped[str] = mapped_column(String(30), default="cutting", index=True)
    rework_unread: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    glass_type: Mapped[str] = mapped_column(String(50))
    specification: Mapped[str] = mapped_column(String(100))
    width_mm: Mapped[int] = mapped_column(Integer)
    height_mm: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    completed_qty: Mapped[int] = mapped_column(Integer, default=0)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class QualityCheckModel(Base):
    __tablename__ = "quality_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    work_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("work_orders.id"), index=True)
    inspector_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    check_type: Mapped[str] = mapped_column(String(30))
    result: Mapped[str] = mapped_column(String(20))
    checked_qty: Mapped[int] = mapped_column(Integer)
    passed_qty: Mapped[int] = mapped_column(Integer)
    defect_qty: Mapped[int] = mapped_column(Integer, default=0)
    defect_details: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    images: Mapped[list[str]] = mapped_column(JSONB, default=list)
    remark: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
