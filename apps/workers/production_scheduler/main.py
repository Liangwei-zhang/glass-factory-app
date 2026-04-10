from __future__ import annotations

from datetime import date
from decimal import Decimal

from loguru import logger
from sqlalchemy import select

from domains.production.scheduler_engine import (
    ProductionLine,
    ProductionSchedulerEngine,
    WorkOrderCandidate,
)
from infra.db.models.events import EventOutboxModel
from infra.db.models.orders import OrderItemModel, OrderModel
from infra.db.models.production import ProductionLineModel, WorkOrderModel
from infra.db.session import build_session_factory
from infra.events.topics import Topics


def _derive_priority(remark: str) -> int:
    normalized = remark.lower()
    if "critical" in normalized or "top-urgent" in normalized:
        return 2
    if "urgent" in normalized or "rush" in normalized:
        return 1
    return 0


async def run_once(
    batch_size: int = 200,
    horizon_days: int = 14,
    target_day: date | None = None,
) -> int:
    start_day = target_day or date.today()
    session_factory = build_session_factory()

    async with session_factory() as session:
        line_result = await session.execute(
            select(ProductionLineModel)
            .where(ProductionLineModel.is_active.is_(True))
            .order_by(ProductionLineModel.line_code.asc())
        )
        line_rows = list(line_result.scalars().all())
        if not line_rows:
            logger.warning("production-scheduler worker skipped: no active production lines")
            return 0

        production_lines = [
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

        candidate_result = await session.execute(
            select(WorkOrderModel, OrderModel, OrderItemModel)
            .join(OrderModel, WorkOrderModel.order_id == OrderModel.id)
            .join(OrderItemModel, WorkOrderModel.order_item_id == OrderItemModel.id)
            .where(
                WorkOrderModel.status.in_(["pending", "in_progress"]),
                WorkOrderModel.scheduled_date.is_(None),
            )
            .order_by(OrderModel.expected_delivery_date.asc(), WorkOrderModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(candidate_result.all())
        if not rows:
            return 0

        candidates: list[WorkOrderCandidate] = []
        work_orders_by_id: dict[str, WorkOrderModel] = {}
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

        engine = ProductionSchedulerEngine(production_lines)
        scheduling_result = engine.schedule(
            candidates=candidates,
            start_date=start_day,
            horizon_days=horizon_days,
        )

        for slot in scheduling_result.scheduled:
            row = work_orders_by_id.get(slot.work_order_id)
            if row is None:
                continue

            row.production_line_id = slot.line_id
            row.scheduled_date = slot.scheduled_date

            session.add(
                EventOutboxModel(
                    topic=Topics.PRODUCTION_SCHEDULED,
                    event_key=row.id,
                    payload={
                        "work_order_id": row.id,
                        "order_id": row.order_id,
                        "line_id": slot.line_id,
                        "scheduled_date": slot.scheduled_date.isoformat(),
                        "sequence": slot.sequence,
                    },
                    headers={"source": "worker.production_scheduler"},
                    status="pending",
                )
            )

        await session.commit()

    if scheduling_result.unschedulable:
        logger.warning(
            "production-scheduler worker unschedulable count={} sample_reason={}",
            len(scheduling_result.unschedulable),
            scheduling_result.unschedulable[0][1],
        )

    logger.info(
        "production-scheduler worker scheduled work orders count={}",
        len(scheduling_result.scheduled),
    )
    return len(scheduling_result.scheduled)
