from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domains.logistics.schema import CreateShipmentRequest, DeliverShipmentRequest, ShipmentView
from domains.logistics.service import LogisticsService

service = LogisticsService()


def _serialize_shipment(view: ShipmentView) -> dict[str, Any]:
    return view.model_dump(mode="json")


async def list_workspace_shipments(
    session: AsyncSession,
    *,
    limit: int = 100,
    status: str | None = None,
    order_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = await service.list_shipments(session, limit=limit, status=status, order_id=order_id)
    return [_serialize_shipment(row) for row in rows]


async def create_workspace_shipment(
    session: AsyncSession,
    *,
    order_id: str,
    carrier_name: str | None,
    tracking_no: str | None,
    vehicle_no: str | None,
    driver_name: str | None,
    driver_phone: str | None,
    shipped_at,
    actor_user_id: str,
) -> dict[str, Any]:
    shipment = await service.create_shipment(
        session,
        CreateShipmentRequest(
            order_id=order_id,
            carrier_name=carrier_name,
            tracking_no=tracking_no,
            vehicle_no=vehicle_no,
            driver_name=driver_name,
            driver_phone=driver_phone,
            shipped_at=shipped_at,
        ),
        actor_user_id=actor_user_id,
    )
    return {"shipment": _serialize_shipment(shipment)}


async def deliver_workspace_shipment(
    session: AsyncSession,
    *,
    shipment_id: str,
    receiver_name: str,
    receiver_phone: str | None,
    delivered_at,
    signature_data_url: str | None,
    actor_user_id: str,
) -> dict[str, Any]:
    shipment = await service.deliver_shipment(
        session,
        shipment_id,
        DeliverShipmentRequest(
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            delivered_at=delivered_at,
            signature_data_url=signature_data_url,
        ),
        actor_user_id=actor_user_id,
    )
    return {"shipment": _serialize_shipment(shipment)}
