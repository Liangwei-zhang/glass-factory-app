from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel
from infra.db.models.finance import ReceivableModel
from infra.db.models.orders import OrderModel
from infra.db.models.production import WorkOrderModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/tasks", tags=["tasks"])
admin_guard = require_roles(["admin", "manager"])


@router.get("")
async def list_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    today = date.today()
    detail_limit = min(limit, 50)

    dead_letter_count = await session.scalar(
        select(func.count(EventOutboxModel.id)).where(
            EventOutboxModel.status.in_(["dead_letter", "failed"])
        )
    )
    overdue_receivable_count = await session.scalar(
        select(func.count(ReceivableModel.id)).where(
            ReceivableModel.status.in_(["unpaid", "partial"]),
            ReceivableModel.due_date < today,
        )
    )
    unscheduled_work_order_count = await session.scalar(
        select(func.count(WorkOrderModel.id)).where(
            WorkOrderModel.status.in_(["pending", "in_progress"]),
            WorkOrderModel.scheduled_date.is_(None),
        )
    )
    pickup_approval_count = await session.scalar(
        select(func.count(OrderModel.id)).where(
            OrderModel.status.in_(["completed", "ready_for_pickup"])
        )
    )

    dead_letters_result = await session.execute(
        select(EventOutboxModel)
        .where(EventOutboxModel.status.in_(["dead_letter", "failed"]))
        .order_by(EventOutboxModel.created_at.desc())
        .limit(detail_limit)
    )
    overdue_receivables_result = await session.execute(
        select(ReceivableModel)
        .where(
            ReceivableModel.status.in_(["unpaid", "partial"]),
            ReceivableModel.due_date < today,
        )
        .order_by(ReceivableModel.due_date.asc())
        .limit(detail_limit)
    )
    unscheduled_work_orders_result = await session.execute(
        select(WorkOrderModel)
        .where(
            WorkOrderModel.status.in_(["pending", "in_progress"]),
            WorkOrderModel.scheduled_date.is_(None),
        )
        .order_by(WorkOrderModel.created_at.asc())
        .limit(detail_limit)
    )
    pickup_queue_result = await session.execute(
        select(OrderModel)
        .where(OrderModel.status.in_(["completed", "ready_for_pickup"]))
        .order_by(OrderModel.updated_at.asc())
        .limit(detail_limit)
    )

    items: list[dict] = []

    for row in dead_letters_result.scalars().all():
        items.append(
            {
                "id": f"event:{row.id}",
                "task_type": "event_retry",
                "priority": "critical",
                "title": "Dead-letter event requires operator action",
                "entity_id": row.id,
                "topic": row.topic,
                "created_at": row.created_at,
                "details": {
                    "attempt_count": row.attempt_count,
                    "max_attempts": row.max_attempts,
                    "last_error": row.last_error,
                },
            }
        )

    for row in overdue_receivables_result.scalars().all():
        items.append(
            {
                "id": f"receivable:{row.id}",
                "task_type": "receivable_overdue",
                "priority": "high",
                "title": "Overdue receivable requires follow-up",
                "entity_id": row.id,
                "due_date": row.due_date,
                "details": {
                    "order_id": row.order_id,
                    "customer_id": row.customer_id,
                    "amount": row.amount,
                    "paid_amount": row.paid_amount,
                    "status": row.status,
                },
            }
        )

    for row in unscheduled_work_orders_result.scalars().all():
        items.append(
            {
                "id": f"work_order:{row.id}",
                "task_type": "schedule_work_order",
                "priority": "normal",
                "title": "Work order pending schedule",
                "entity_id": row.id,
                "created_at": row.created_at,
                "details": {
                    "work_order_no": row.work_order_no,
                    "status": row.status,
                    "glass_type": row.glass_type,
                    "specification": row.specification,
                    "quantity": row.quantity,
                },
            }
        )

    for row in pickup_queue_result.scalars().all():
        items.append(
            {
                "id": f"order:{row.id}",
                "task_type": "pickup_approval",
                "priority": "normal",
                "title": "Order is waiting for pickup approval",
                "entity_id": row.id,
                "created_at": row.updated_at,
                "details": {
                    "order_no": row.order_no,
                    "status": row.status,
                    "expected_delivery_date": row.expected_delivery_date,
                },
            }
        )

    return {
        "items": items[:limit],
        "summary": {
            "dead_letter_events": int(dead_letter_count or 0),
            "overdue_receivables": int(overdue_receivable_count or 0),
            "unscheduled_work_orders": int(unscheduled_work_order_count or 0),
            "pickup_approvals": int(pickup_approval_count or 0),
        },
    }
