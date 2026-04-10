from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domains.orders.schema import CreateOrderRequest
from infra.db.models.orders import OrderItemModel, OrderModel


class OrdersRepository:
    async def get_by_idempotency_key(
        self,
        session: AsyncSession,
        idempotency_key: str,
    ) -> OrderModel | None:
        stmt = (
            select(OrderModel)
            .where(OrderModel.idempotency_key == idempotency_key)
            .options(selectinload(OrderModel.items))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_order(
        self,
        session: AsyncSession,
        order_no: str,
        payload: CreateOrderRequest,
        reservation_ids: list[str],
    ) -> OrderModel:
        order = OrderModel(
            order_no=order_no,
            customer_id=payload.customer_id,
            status="pending",
            priority=payload.priority,
            total_amount=Decimal("0"),
            total_quantity=0,
            total_area_sqm=Decimal("0"),
            delivery_address=payload.delivery_address,
            expected_delivery_date=payload.expected_delivery_date,
            reservation_ids=reservation_ids,
            remark=payload.remark,
            idempotency_key=payload.idempotency_key,
        )

        total_amount = Decimal("0")
        total_quantity = 0
        total_area_sqm = Decimal("0")

        for item in payload.items:
            area_sqm = (Decimal(item.width_mm) * Decimal(item.height_mm)) / Decimal("1000000")
            subtotal = item.unit_price * item.quantity
            order.items.append(
                OrderItemModel(
                    product_id=item.product_id,
                    product_name=item.product_name,
                    glass_type=item.glass_type,
                    specification=item.specification,
                    width_mm=item.width_mm,
                    height_mm=item.height_mm,
                    area_sqm=area_sqm,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    subtotal=subtotal,
                    process_requirements=item.process_requirements,
                )
            )
            total_quantity += item.quantity
            total_area_sqm += area_sqm * item.quantity
            total_amount += subtotal

        order.total_quantity = total_quantity
        order.total_area_sqm = total_area_sqm
        order.total_amount = total_amount

        session.add(order)
        await session.flush()
        await session.refresh(order)
        return order

    async def get_order(self, session: AsyncSession, order_id: str) -> OrderModel | None:
        stmt = (
            select(OrderModel)
            .where(OrderModel.id == order_id)
            .options(selectinload(OrderModel.items))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_orders(self, session: AsyncSession, limit: int = 50) -> list[OrderModel]:
        stmt = (
            select(OrderModel)
            .options(selectinload(OrderModel.items))
            .order_by(OrderModel.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_order_status(
        self,
        session: AsyncSession,
        order_id: str,
        status: str,
        confirmed_at: datetime | None = None,
        pickup_approved_at: datetime | None = None,
        pickup_approved_by: str | None = None,
        picked_up_at: datetime | None = None,
        picked_up_by: str | None = None,
        pickup_signer_name: str | None = None,
        pickup_signature_key: str | None = None,
        drawing_object_key: str | None = None,
        drawing_original_name: str | None = None,
        cancelled_at: datetime | None = None,
        cancelled_reason: str | None = None,
    ) -> OrderModel | None:
        row = await self.get_order(session, order_id)
        if row is None:
            return None

        row.status = status
        if confirmed_at is not None:
            row.confirmed_at = confirmed_at
        if pickup_approved_at is not None:
            row.pickup_approved_at = pickup_approved_at
        if pickup_approved_by is not None:
            row.pickup_approved_by = pickup_approved_by
        if picked_up_at is not None:
            row.picked_up_at = picked_up_at
        if picked_up_by is not None:
            row.picked_up_by = picked_up_by
        if pickup_signer_name is not None:
            row.pickup_signer_name = pickup_signer_name
        if pickup_signature_key is not None:
            row.pickup_signature_key = pickup_signature_key
        if drawing_object_key is not None:
            row.drawing_object_key = drawing_object_key
        if drawing_original_name is not None:
            row.drawing_original_name = drawing_original_name
        if cancelled_at is not None:
            row.cancelled_at = cancelled_at
        if cancelled_reason is not None:
            row.cancelled_reason = cancelled_reason
        row.version += 1

        await session.flush()
        await session.refresh(row)
        return row
