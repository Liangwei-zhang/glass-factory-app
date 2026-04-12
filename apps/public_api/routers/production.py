from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.production.schema import WorkOrderView
from domains.production.service import ProductionService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.rbac import require_roles

router = APIRouter(prefix="/production", tags=["production"])
service = ProductionService()
operator_guard = require_roles(["operator", "manager", "admin"])


@router.get("/work-orders", response_model=list[WorkOrderView])
async def list_work_orders(
    limit: int = Query(default=100, ge=1, le=500),
    stage: str | None = Query(default=None),
    mine: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> list[WorkOrderView]:
    normalized_stage = stage.strip().lower() if stage else None
    assignee_user_id = user.user_id if mine else None
    include_unassigned = mine and bool(user.stage)
    return await service.list_work_orders(
        session,
        limit=limit,
        step_key=normalized_stage,
        assignee_user_id=assignee_user_id,
        include_unassigned=include_unassigned,
    )


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderView)
async def get_work_order(
    work_order_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> WorkOrderView:
    _ = user
    work_order = await service.get_work_order(session, work_order_id=work_order_id)
    if work_order is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    return work_order


@router.get("/schedule", response_model=list[WorkOrderView])
async def list_schedule(
    day: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    stage: str | None = Query(default=None),
    mine: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(operator_guard),
) -> list[WorkOrderView]:
    normalized_stage = stage.strip().lower() if stage else None
    assignee_user_id = user.user_id if mine else None
    include_unassigned = mine and bool(user.stage)
    return await service.list_schedule(
        session,
        day=day,
        limit=limit,
        step_key=normalized_stage,
        assignee_user_id=assignee_user_id,
        include_unassigned=include_unassigned,
    )
