from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.logistics.schema import CreateShipmentRequest, DeliverShipmentRequest, ShipmentView
from domains.logistics.service import LogisticsService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key
from infra.security.rbac import require_scopes

router = APIRouter(prefix="/logistics", tags=["logistics"])
service = LogisticsService()
write_guard = require_scopes(["logistics:write"])


@router.get("/shipments", response_model=list[ShipmentView])
async def list_shipments(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    order_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[ShipmentView]:
    _ = user
    return await service.list_shipments(
        session,
        limit=limit,
        status=status,
        order_id=order_id,
    )


@router.get("/tracking/{no}", response_model=ShipmentView)
async def get_tracking(
    no: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> ShipmentView:
    _ = user
    return await service.get_tracking(session, tracking_no=no)


@router.post("/shipments", response_model=ShipmentView, status_code=201)
async def create_shipment(
    payload: CreateShipmentRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ShipmentView:
    await enforce_idempotency_key("logistics:shipments:create", idempotency_key)
    return await service.create_shipment(session, payload, actor_user_id=user.user_id)


@router.post("/shipments/{shipment_id}/deliver", response_model=ShipmentView)
async def deliver_shipment(
    shipment_id: str,
    payload: DeliverShipmentRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ShipmentView:
    await enforce_idempotency_key("logistics:shipments:deliver", idempotency_key)
    return await service.deliver_shipment(
        session,
        shipment_id,
        payload,
        actor_user_id=user.user_id,
    )
