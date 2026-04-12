from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from domains.inventory.service import InventoryService
from infra.core.hooks import (
    execute_after_rollback_hooks,
    pop_after_commit_hooks,
    pop_after_rollback_hooks,
)
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel
from infra.db.session import build_session_factory
from infra.events.topics import Topics

LOW_STOCK_ALERT_COOLDOWN_MINUTES = 30


async def run_once(
    batch_size: int = 500,
    alert_cooldown_minutes: int = LOW_STOCK_ALERT_COOLDOWN_MINUTES,
) -> int:
    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(minutes=alert_cooldown_minutes)
    inventory_service = InventoryService()

    session_factory = build_session_factory()
    async with session_factory() as session:
        try:
            expired_release_count = await inventory_service.release_expired_reservations(
                session,
                limit=batch_size,
            )

            result = await session.execute(
                select(InventoryModel)
                .order_by(InventoryModel.updated_at.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            rows = list(result.scalars().all())

            synced_count = 0
            low_stock_alert_count = 0

            for row in rows:
                expected_total = row.available_qty + row.reserved_qty
                if row.total_qty != expected_total:
                    row.total_qty = expected_total
                    row.version += 1
                    synced_count += 1

                if row.available_qty > row.safety_stock:
                    continue

                existing_alert = await session.execute(
                    select(EventOutboxModel.id)
                    .where(
                        EventOutboxModel.topic == Topics.INVENTORY_LOW_STOCK,
                        EventOutboxModel.event_key == row.product_id,
                        EventOutboxModel.created_at >= cooldown_cutoff,
                    )
                    .limit(1)
                )
                if existing_alert.scalar_one_or_none() is not None:
                    continue

                session.add(
                    EventOutboxModel(
                        topic=Topics.INVENTORY_LOW_STOCK,
                        event_key=row.product_id,
                        payload={
                            "product_id": row.product_id,
                            "available_qty": row.available_qty,
                            "reserved_qty": row.reserved_qty,
                            "total_qty": row.total_qty,
                            "safety_stock": row.safety_stock,
                            "warehouse_code": row.warehouse_code,
                        },
                        headers={"source": "worker.inventory_sync"},
                        status="pending",
                    )
                )
                low_stock_alert_count += 1

            await session.commit()
            pop_after_rollback_hooks(session)
        except Exception:
            pop_after_commit_hooks(session)
            await session.rollback()
            await execute_after_rollback_hooks(session)
            raise

    changed = synced_count + low_stock_alert_count + expired_release_count
    if changed:
        logger.info(
            "inventory-sync worker updated rows synced={} low_stock_alerts={} expired_releases={}",
            synced_count,
            low_stock_alert_count,
            expired_release_count,
        )

    return changed
