from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from infra.db.models.events import EventOutboxModel
from infra.db.models.orders import OrderModel
from infra.db.session import build_session_factory
from infra.events.topics import Topics

ORDER_TIMEOUT_MINUTES = 30


async def run_once(batch_size: int = 200, timeout_minutes: int = ORDER_TIMEOUT_MINUTES) -> int:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=timeout_minutes)

    session_factory = build_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(OrderModel)
            .where(
                OrderModel.status == "pending",
                OrderModel.confirmed_at.is_(None),
                OrderModel.created_at <= cutoff,
            )
            .order_by(OrderModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        stale_orders = list(result.scalars().all())

        for row in stale_orders:
            row.status = "cancelled"
            row.cancelled_at = now
            row.cancelled_reason = "auto_cancelled_by_timeout"
            row.version += 1
            session.add(
                EventOutboxModel(
                    topic=Topics.ORDER_CANCELLED,
                    event_key=row.id,
                    payload={
                        "order_id": row.id,
                        "order_no": row.order_no,
                        "status": row.status,
                        "reason": "timeout_auto_cancel",
                    },
                    headers={"source": "worker.order_timeout"},
                    status="pending",
                )
            )

        await session.commit()

    if stale_orders:
        logger.info(
            "order-timeout worker cancelled stale pending orders count={} cutoff={}",
            len(stale_orders),
            cutoff.isoformat(),
        )

    return len(stale_orders)
