from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from loguru import logger
from sqlalchemy import select

from infra.db.models.events import EventOutboxModel
from infra.db.models.notifications import NotificationModel
from infra.db.session import build_session_factory
from infra.storage.object_storage import ObjectStorage

EVENT_RETENTION_DAYS = 30
READ_NOTIFICATION_RETENTION_DAYS = 90


def _serialize_event(row: EventOutboxModel) -> dict:
    return {
        "id": row.id,
        "topic": row.topic,
        "event_key": row.event_key,
        "payload": row.payload,
        "headers": row.headers,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


async def run_once(
    event_batch_size: int = 500,
    notification_batch_size: int = 500,
    event_retention_days: int = EVENT_RETENTION_DAYS,
    read_notification_retention_days: int = READ_NOTIFICATION_RETENTION_DAYS,
) -> int:
    now = datetime.now(timezone.utc)
    event_cutoff = now - timedelta(days=event_retention_days)
    notification_cutoff = now - timedelta(days=read_notification_retention_days)

    session_factory = build_session_factory()
    async with session_factory() as session:
        event_result = await session.execute(
            select(EventOutboxModel)
            .where(
                EventOutboxModel.status.in_(["published", "dead_letter"]),
                EventOutboxModel.created_at < event_cutoff,
            )
            .order_by(EventOutboxModel.created_at.asc())
            .limit(event_batch_size)
            .with_for_update(skip_locked=True)
        )
        old_events = list(event_result.scalars().all())

        archived_event_count = 0
        if old_events:
            archive_payload = [_serialize_event(row) for row in old_events]
            storage = ObjectStorage()
            archive_key = f"event-outbox/{now:%Y/%m/%d}/events-{uuid4().hex}.json"
            await storage.put_bytes(
                bucket="archive",
                key=archive_key,
                payload=json.dumps(archive_payload, ensure_ascii=True, default=str).encode("utf-8"),
            )
            for row in old_events:
                await session.delete(row)
            archived_event_count = len(old_events)

        notification_result = await session.execute(
            select(NotificationModel)
            .where(
                NotificationModel.is_read.is_(True),
                NotificationModel.created_at < notification_cutoff,
            )
            .order_by(NotificationModel.created_at.asc())
            .limit(notification_batch_size)
            .with_for_update(skip_locked=True)
        )
        old_notifications = list(notification_result.scalars().all())
        for notification in old_notifications:
            await session.delete(notification)

        await session.commit()

    deleted_notification_count = len(old_notifications)
    total = archived_event_count + deleted_notification_count
    if total:
        logger.info(
            "retention worker archived events={} deleted_read_notifications={}",
            archived_event_count,
            deleted_notification_count,
        )

    return total
