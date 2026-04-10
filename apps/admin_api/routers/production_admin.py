from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.production.scheduler_engine import (
    ProductionLine,
    ProductionSchedulerEngine,
    WorkOrderCandidate,
)
from infra.core.errors import AppError
from infra.db.models.orders import OrderItemModel, OrderModel
from infra.db.models.production import ProductionLineModel, WorkOrderModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/production", tags=["production-admin"])
admin_guard = require_roles(["admin", "supervisor", "manager"])


def _derive_priority(remark: str) -> int:
    normalized = remark.lower()
    if "critical" in normalized or "top-urgent" in normalized:
        return 2
    if "urgent" in normalized or "rush" in normalized:
        return 1
    return 0


class ScheduleRequest(BaseModel):
    work_order_ids: list[str] = Field(default_factory=list)
    day: date | None = None
    horizon_days: int = Field(default=14, ge=1, le=30)
    limit: int = Field(default=200, ge=1, le=1000)


class ProductionLineUpdateRequest(BaseModel):
    line_name: str | None = None
    supported_glass_types: list[str] | None = None
    max_width_mm: int | None = Field(default=None, ge=100)
    max_height_mm: int | None = Field(default=None, ge=100)
    daily_capacity_sqm: Decimal | None = Field(default=None, gt=0)
    supported_processes: list[str] | None = None
    is_active: bool | None = None


@router.get("/lines")
async def list_production_lines(
    limit: int = Query(default=100, ge=1, le=500),
    active_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    stmt = select(ProductionLineModel)
    if active_only:
        stmt = stmt.where(ProductionLineModel.is_active.is_(True))

    lines_result = await session.execute(
        stmt.order_by(ProductionLineModel.line_code.asc()).limit(limit)
    )
    lines = lines_result.scalars().all()

    workload_result = await session.execute(
        select(WorkOrderModel.production_line_id, func.count(WorkOrderModel.id))
        .where(WorkOrderModel.status.in_(["pending", "in_progress"]))
        .group_by(WorkOrderModel.production_line_id)
    )
    workload_map = {
        line_id: int(count) for line_id, count in workload_result.all() if line_id is not None
    }

    return {
        "items": [
            {
                "id": row.id,
                "line_code": row.line_code,
                "line_name": row.line_name,
                "supported_glass_types": row.supported_glass_types,
                "max_width_mm": row.max_width_mm,
                "max_height_mm": row.max_height_mm,
                "daily_capacity_sqm": row.daily_capacity_sqm,
                "supported_processes": row.supported_processes,
                "is_active": row.is_active,
                "active_work_orders": workload_map.get(row.id, 0),
                "created_at": row.created_at,
            }
            for row in lines
        ]
    }


@router.post("/schedule")
async def execute_schedule(
    payload: ScheduleRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    target_day = payload.day or date.today()

    line_result = await session.execute(
        select(ProductionLineModel)
        .where(ProductionLineModel.is_active.is_(True))
        .order_by(ProductionLineModel.line_code.asc())
    )
    line_rows = list(line_result.scalars().all())
    if not line_rows:
        raise AppError(
            code="PRODUCTION_LINE_NOT_CONFIGURED",
            message="No active production lines are configured.",
            status_code=409,
        )

    scheduler_engine = ProductionSchedulerEngine(
        [
            ProductionLine(
                line_id=row.id,
                line_name=row.line_name,
                supported_glass_types=set(row.supported_glass_types or []),
                max_width_mm=row.max_width_mm,
                max_height_mm=row.max_height_mm,
                daily_capacity_sqm=Decimal(row.daily_capacity_sqm),
                supported_processes=set(row.supported_processes or []),
            )
            for row in line_rows
        ]
    )

    stmt = (
        select(WorkOrderModel, OrderModel, OrderItemModel)
        .join(OrderModel, WorkOrderModel.order_id == OrderModel.id)
        .join(OrderItemModel, WorkOrderModel.order_item_id == OrderItemModel.id)
        .where(WorkOrderModel.status.in_(["pending", "in_progress"]))
    )
    if payload.work_order_ids:
        stmt = stmt.where(WorkOrderModel.id.in_(payload.work_order_ids))

    result = await session.execute(
        stmt.order_by(
            OrderModel.expected_delivery_date.asc(), WorkOrderModel.created_at.asc()
        ).limit(payload.limit)
    )
    rows = result.all()

    found_ids = [work_order.id for work_order, _, _ in rows]
    found_id_set = set(found_ids)
    work_orders_by_id: dict[str, WorkOrderModel] = {}
    candidates: list[WorkOrderCandidate] = []
    for work_order, order, order_item in rows:
        area_sqm = (
            Decimal(work_order.width_mm)
            * Decimal(work_order.height_mm)
            * Decimal(work_order.quantity)
        ) / Decimal("1000000")
        candidates.append(
            WorkOrderCandidate(
                work_order_id=work_order.id,
                order_no=order.order_no,
                glass_type=work_order.glass_type,
                specification=work_order.specification,
                width_mm=work_order.width_mm,
                height_mm=work_order.height_mm,
                quantity=work_order.quantity,
                area_sqm=area_sqm,
                process_requirements=order_item.process_requirements or "",
                expected_delivery_date=order.expected_delivery_date.date(),
                priority=_derive_priority(order.remark or ""),
            )
        )
        work_orders_by_id[work_order.id] = work_order

    scheduling_result = scheduler_engine.schedule(
        candidates=candidates,
        start_date=target_day,
        horizon_days=payload.horizon_days,
    )
    missing_requested_ids = [
        work_order_id
        for work_order_id in payload.work_order_ids
        if work_order_id not in found_id_set
    ]

    for slot in scheduling_result.scheduled:
        row = work_orders_by_id.get(slot.work_order_id)
        if row is None:
            continue
        row.scheduled_date = slot.scheduled_date
        row.production_line_id = slot.line_id

    await session.flush()

    return {
        "scheduled_day": target_day,
        "scheduled_count": len(scheduling_result.scheduled_work_order_ids),
        "scheduled_work_order_ids": scheduling_result.scheduled_work_order_ids,
        "scheduled_slots": [
            {
                "work_order_id": slot.work_order_id,
                "line_id": slot.line_id,
                "scheduled_date": slot.scheduled_date,
                "sequence": slot.sequence,
            }
            for slot in scheduling_result.scheduled
        ],
        "unscheduled_work_order_ids": scheduling_result.unscheduled_work_order_ids
        + missing_requested_ids,
    }


@router.put("/lines/{line_id}")
async def update_production_line(
    payload: ProductionLineUpdateRequest,
    line_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    line = await session.get(ProductionLineModel, line_id)
    if line is None:
        raise AppError(
            code="PRODUCTION_LINE_NOT_FOUND",
            message=f"Production line not found: {line_id}",
            status_code=404,
        )

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(line, field, value)

    await session.flush()

    return {
        "id": line.id,
        "line_code": line.line_code,
        "line_name": line.line_name,
        "supported_glass_types": line.supported_glass_types,
        "max_width_mm": line.max_width_mm,
        "max_height_mm": line.max_height_mm,
        "daily_capacity_sqm": line.daily_capacity_sqm,
        "supported_processes": line.supported_processes,
        "is_active": line.is_active,
    }
