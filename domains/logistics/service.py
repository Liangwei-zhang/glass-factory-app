from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from domains.logistics.errors import ShipmentNotFound
from domains.logistics.repository import LogisticsRepository
from domains.logistics.schema import CreateShipmentRequest, DeliverShipmentRequest, ShipmentView
from domains.orders.schema import OrderStatus, can_transition_order_status
from infra.core.errors import AppError, ErrorCode
from infra.db.models.logistics import ShipmentModel
from infra.db.models.orders import OrderModel
from infra.events.outbox import OutboxPublisher
from infra.events.topics import Topics
from infra.signatures import build_signature_storage_key, decode_signature_data_url
from infra.storage.object_storage import ObjectStorage

SHIPPABLE_ORDER_STATUSES = {"completed", "ready_for_pickup", "picked_up", "shipping", "delivered"}


class LogisticsService:
    def __init__(self, repository: LogisticsRepository | None = None) -> None:
        self.repository = repository or LogisticsRepository()

    async def create_shipment(
        self,
        session: AsyncSession,
        payload: CreateShipmentRequest,
        *,
        actor_user_id: str,
    ) -> ShipmentView:
        order = await session.get(OrderModel, payload.order_id)
        if order is None:
            raise AppError(
                code=ErrorCode.ORDER_NOT_FOUND,
                message="Order not found.",
                status_code=404,
                details={"order_id": payload.order_id},
            )

        if order.status not in SHIPPABLE_ORDER_STATUSES:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Order is not ready for shipment.",
                status_code=409,
                details={"order_id": order.id, "status": order.status},
            )

        row = await self.repository.get_latest_shipment_by_order(session, order.id)
        shipped_at = payload.shipped_at or datetime.now(timezone.utc)
        tracking_no = (payload.tracking_no or order.order_no).strip() or order.order_no

        if row is None:
            row = ShipmentModel(
                shipment_no=f"SH-{order.order_no}",
                order_id=order.id,
                status="shipped",
                carrier_name=(payload.carrier_name or "").strip() or None,
                tracking_no=tracking_no,
                vehicle_no=(payload.vehicle_no or "").strip() or None,
                driver_name=(payload.driver_name or "").strip() or None,
                driver_phone=(payload.driver_phone or "").strip() or None,
                shipped_at=shipped_at,
            )
            session.add(row)
        elif row.status != "delivered":
            row.status = "shipped"
            row.carrier_name = (payload.carrier_name or row.carrier_name or "").strip() or None
            row.tracking_no = tracking_no
            row.vehicle_no = (payload.vehicle_no or row.vehicle_no or "").strip() or None
            row.driver_name = (payload.driver_name or row.driver_name or "").strip() or None
            row.driver_phone = (payload.driver_phone or row.driver_phone or "").strip() or None
            row.shipped_at = row.shipped_at or shipped_at

        if can_transition_order_status(order.status, OrderStatus.SHIPPING):
            order.status = OrderStatus.SHIPPING.value

        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.LOGISTICS_SHIPPED,
            key=row.id,
            payload={
                "shipment_id": row.id,
                "shipment_no": row.shipment_no,
                "order_id": order.id,
                "order_no": order.order_no,
                "tracking_no": row.tracking_no,
                "status": row.status,
                "actor_user_id": actor_user_id,
            },
        )
        await outbox.publish_after_commit(
            topic=Topics.ORDER_SHIPPING,
            key=order.id,
            payload={
                "order_id": order.id,
                "order_no": order.order_no,
                "shipment_id": row.id,
                "shipment_no": row.shipment_no,
                "tracking_no": row.tracking_no,
                "actor_user_id": actor_user_id,
            },
        )

        return ShipmentView.model_validate(row)

    async def deliver_shipment(
        self,
        session: AsyncSession,
        shipment_id: str,
        payload: DeliverShipmentRequest,
        *,
        actor_user_id: str,
    ) -> ShipmentView:
        row = await self.repository.get_shipment(session, shipment_id)
        if row is None:
            raise ShipmentNotFound(shipment_id)

        if row.status != "delivered":
            signature_key = row.signature_image
            if payload.signature_data_url:
                signature_bytes, extension = decode_signature_data_url(payload.signature_data_url)
                signature_key = build_signature_storage_key(
                    scope="shipments",
                    entity_id=shipment_id,
                    extension=extension,
                )
                storage = ObjectStorage()
                await storage.put_bytes(
                    bucket="signatures",
                    key=signature_key,
                    payload=signature_bytes,
                )

            row.status = "delivered"
            row.delivered_at = payload.delivered_at or datetime.now(timezone.utc)
            row.receiver_name = payload.receiver_name.strip()
            row.receiver_phone = (payload.receiver_phone or "").strip() or None
            row.signature_image = signature_key
            row.shipped_at = row.shipped_at or row.delivered_at
            await session.flush()

            order = await session.get(OrderModel, row.order_id)
            if order is not None and order.status != OrderStatus.PICKED_UP.value:
                if can_transition_order_status(order.status, OrderStatus.DELIVERED):
                    order.status = OrderStatus.DELIVERED.value
                    await session.flush()
            outbox = OutboxPublisher(session)
            await outbox.publish_after_commit(
                topic=Topics.LOGISTICS_DELIVERED,
                key=row.id,
                payload={
                    "shipment_id": row.id,
                    "shipment_no": row.shipment_no,
                    "order_id": row.order_id,
                    "order_no": order.order_no if order is not None else None,
                    "status": row.status,
                    "receiver_name": row.receiver_name,
                    "actor_user_id": actor_user_id,
                },
            )
            await outbox.publish_after_commit(
                topic=Topics.ORDER_DELIVERED,
                key=row.order_id,
                payload={
                    "order_id": row.order_id,
                    "order_no": order.order_no if order is not None else None,
                    "shipment_id": row.id,
                    "shipment_no": row.shipment_no,
                    "receiver_name": row.receiver_name,
                    "actor_user_id": actor_user_id,
                },
            )

        return ShipmentView.model_validate(row)

    async def list_shipments(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        order_id: str | None = None,
    ) -> list[ShipmentView]:
        rows = await self.repository.list_shipments(
            session,
            limit=limit,
            status=status,
            order_id=order_id,
        )
        return [ShipmentView.model_validate(row) for row in rows]

    async def get_tracking(self, session: AsyncSession, tracking_no: str) -> ShipmentView:
        row = await self.repository.get_tracking(session, tracking_no=tracking_no)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Shipment tracking not found.",
                status_code=404,
                details={"tracking_no": tracking_no},
            )
        return ShipmentView.model_validate(row)
