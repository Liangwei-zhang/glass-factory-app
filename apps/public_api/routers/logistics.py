from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.logistics.schema import ShipmentView
from domains.logistics.service import LogisticsService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user

router = APIRouter(prefix="/logistics", tags=["logistics"])
service = LogisticsService()


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
