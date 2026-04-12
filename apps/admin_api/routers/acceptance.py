from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.logistics import ShipmentModel
from infra.db.models.orders import OrderModel
from infra.db.models.production import QualityCheckModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/acceptance", tags=["acceptance"])
admin_guard = require_roles(["admin", "manager"])


@router.get("")
async def get_acceptance_status(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    ready_for_pickup_count = await session.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.status.in_(["completed", "ready_for_pickup"]))
    )
    picked_up_count = await session.scalar(
        select(func.count(OrderModel.id)).where(OrderModel.status == "picked_up")
    )
    in_transit_shipment_count = await session.scalar(
        select(func.count(ShipmentModel.id)).where(ShipmentModel.status.in_(["pending", "shipped"]))
    )
    failed_quality_check_count = await session.scalar(
        select(func.count(QualityCheckModel.id)).where(
            QualityCheckModel.result.in_(["failed", "rework", "rejected"])
        )
    )

    ready_for_pickup_result = await session.execute(
        select(OrderModel)
        .where(OrderModel.status.in_(["completed", "ready_for_pickup"]))
        .order_by(OrderModel.updated_at.desc())
        .limit(limit)
    )
    failed_checks_result = await session.execute(
        select(QualityCheckModel)
        .where(QualityCheckModel.result.in_(["failed", "rework", "rejected"]))
        .order_by(QualityCheckModel.checked_at.desc())
        .limit(limit)
    )

    status = "ok"
    if (failed_quality_check_count or 0) > 0:
        status = "attention"

    return {
        "status": status,
        "kpis": {
            "ready_for_pickup_orders": int(ready_for_pickup_count or 0),
            "picked_up_orders": int(picked_up_count or 0),
            "in_transit_shipments": int(in_transit_shipment_count or 0),
            "failed_quality_checks": int(failed_quality_check_count or 0),
        },
        "ready_for_pickup": [
            {
                "id": row.id,
                "order_no": row.order_no,
                "customer_id": row.customer_id,
                "status": row.status,
                "expected_delivery_date": row.expected_delivery_date,
                "updated_at": row.updated_at,
            }
            for row in ready_for_pickup_result.scalars().all()
        ],
        "failed_checks": [
            {
                "id": row.id,
                "work_order_id": row.work_order_id,
                "inspector_id": row.inspector_id,
                "check_type": row.check_type,
                "result": row.result,
                "defect_qty": row.defect_qty,
                "remark": row.remark,
                "checked_at": row.checked_at,
            }
            for row in failed_checks_result.scalars().all()
        ],
    }
