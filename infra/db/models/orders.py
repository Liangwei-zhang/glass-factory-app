from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infra.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderModel(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0"))
    total_quantity: Mapped[int] = mapped_column(Integer, default=0)
    total_area_sqm: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    delivery_address: Mapped[str] = mapped_column(Text)
    expected_delivery_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pickup_approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pickup_signer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pickup_signature_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    drawing_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    drawing_original_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reservation_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    remark: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    items: Mapped[list[OrderItemModel]] = relationship(
        "OrderItemModel", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItemModel(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), index=True)

    product_name: Mapped[str] = mapped_column(String(200))
    glass_type: Mapped[str] = mapped_column(String(50))
    specification: Mapped[str] = mapped_column(String(100))
    width_mm: Mapped[int] = mapped_column(Integer)
    height_mm: Mapped[int] = mapped_column(Integer)
    area_sqm: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    process_requirements: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    order: Mapped[OrderModel] = relationship("OrderModel", back_populates="items")
