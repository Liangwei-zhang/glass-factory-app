from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.orders import OrderModel
from infra.db.models.production import ProductionLineModel, WorkOrderModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_guard = require_roles(["admin", "manager"])


@router.get("/overview")
async def analytics_overview(
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    now = datetime.now(timezone.utc)
    start_today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end_today = start_today + timedelta(days=1)

    orders_today = await session.scalar(
        select(func.count(OrderModel.id)).where(
            OrderModel.created_at >= start_today,
            OrderModel.created_at < end_today,
        )
    )
    total_orders = await session.scalar(select(func.count(OrderModel.id)))
    pending_orders = await session.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.status == "pending")
    )
    producing_orders = await session.scalar(
        select(func.count(OrderModel.id)).where(
            OrderModel.status.in_(["producing", "in_production"])
        )
    )
    completed_orders = await session.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.status == "completed")
    )
    active_work_orders = await session.scalar(
        select(func.count(WorkOrderModel.id)).where(
            WorkOrderModel.status.in_(["pending", "in_progress"])
        )
    )

    return {
        "kpis": {
            "orders_today": int(orders_today or 0),
            "total_orders": int(total_orders or 0),
            "pending_orders": int(pending_orders or 0),
            "producing_orders": int(producing_orders or 0),
            "completed_orders": int(completed_orders or 0),
            "active_work_orders": int(active_work_orders or 0),
        },
        "generated_at": now,
    }


@router.get("/production")
async def analytics_production(
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    status_rows = await session.execute(
        select(WorkOrderModel.status, func.count(WorkOrderModel.id))
        .group_by(WorkOrderModel.status)
        .order_by(WorkOrderModel.status.asc())
    )
    status_breakdown = {status: int(count) for status, count in status_rows.all()}

    line_rows = await session.execute(
        select(
            ProductionLineModel.id,
            ProductionLineModel.line_code,
            ProductionLineModel.line_name,
            func.count(WorkOrderModel.id),
        )
        .select_from(ProductionLineModel)
        .join(
            WorkOrderModel,
            WorkOrderModel.production_line_id == ProductionLineModel.id,
            isouter=True,
        )
        .group_by(
            ProductionLineModel.id,
            ProductionLineModel.line_code,
            ProductionLineModel.line_name,
        )
        .order_by(ProductionLineModel.line_code.asc())
    )

    return {
        "status_breakdown": status_breakdown,
        "lines": [
            {
                "line_id": line_id,
                "line_code": line_code,
                "line_name": line_name,
                "work_order_count": int(work_order_count),
            }
            for line_id, line_code, line_name, work_order_count in line_rows.all()
        ],
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/sales")
async def analytics_sales(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    now = datetime.now(timezone.utc)
    start_at = now - timedelta(days=days)

    order_count = await session.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.created_at >= start_at)
    )
    total_sales = await session.scalar(
        select(func.coalesce(func.sum(OrderModel.total_amount), Decimal("0"))).where(
            OrderModel.created_at >= start_at
        )
    )
    status_rows = await session.execute(
        select(OrderModel.status, func.count(OrderModel.id))
        .where(OrderModel.created_at >= start_at)
        .group_by(OrderModel.status)
        .order_by(OrderModel.status.asc())
    )

    total_orders_int = int(order_count or 0)
    total_sales_decimal = total_sales or Decimal("0")
    avg_order_amount = Decimal("0")
    if total_orders_int > 0:
        avg_order_amount = total_sales_decimal / total_orders_int

    return {
        "window_days": days,
        "orders": total_orders_int,
        "total_sales": total_sales_decimal,
        "avg_order_amount": avg_order_amount,
        "status_breakdown": {status: int(count) for status, count in status_rows.all()},
        "generated_at": now,
    }
