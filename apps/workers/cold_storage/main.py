from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from loguru import logger
from sqlalchemy import select

from infra.db.models.orders import OrderModel
from infra.db.session import build_session_factory
from infra.storage.object_storage import ObjectStorage

COLD_STORAGE_AFTER_DAYS = 180


def _build_order_archive_row(row: OrderModel) -> dict:
    return {
        "id": row.id,
        "order_no": row.order_no,
        "customer_id": row.customer_id,
        "status": row.status,
        "total_amount": str(row.total_amount),
        "total_quantity": row.total_quantity,
        "total_area_sqm": str(row.total_area_sqm),
        "expected_delivery_date": row.expected_delivery_date.isoformat(),
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "cancelled_reason": row.cancelled_reason,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def run_once(
    batch_size: int = 200,
    archive_after_days: int = COLD_STORAGE_AFTER_DAYS,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=archive_after_days)
    archive_marker_prefix = "[cold-archived:"

    session_factory = build_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(OrderModel)
            .where(
                OrderModel.status.in_(["completed", "cancelled"]),
                OrderModel.updated_at < cutoff,
                ~OrderModel.remark.contains(archive_marker_prefix),
            )
            .order_by(OrderModel.updated_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())
        if not rows:
            return 0

        archive_payload = [_build_order_archive_row(row) for row in rows]
        storage = ObjectStorage()
        archive_time = datetime.now(timezone.utc)
        archive_key = f"orders/{archive_time:%Y/%m/%d}/orders-{uuid4().hex}.json"
        await storage.put_bytes(
            bucket="cold-storage",
            key=archive_key,
            payload=json.dumps(archive_payload, ensure_ascii=True).encode("utf-8"),
        )

        marker = f"{archive_marker_prefix}{archive_time.isoformat()}]"
        for row in rows:
            row.remark = f"{row.remark}\n{marker}" if row.remark else marker

        await session.commit()

    logger.info("cold-storage worker archived orders count={} key={}", len(rows), archive_key)
    return len(rows)
