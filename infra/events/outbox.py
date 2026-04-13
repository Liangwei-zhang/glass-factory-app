from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel

REPLAYABLE_OUTBOX_STATUSES = ("failed", "dead_letter")


class OutboxPublisher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish_after_commit(
        self,
        topic: str,
        payload: dict[str, Any],
        key: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> EventOutboxModel:
        event = EventOutboxModel(
            topic=topic,
            event_key=key,
            payload=payload,
            headers=headers or {},
            status="pending",
            occurred_at=datetime.now(timezone.utc),
        )
        self.session.add(event)
        await self.session.flush()
        return event


async def claim_pending_events(session: AsyncSession, limit: int = 100) -> list[EventOutboxModel]:
    result = await session.execute(
        select(EventOutboxModel)
        .where(EventOutboxModel.status == "pending")
        .order_by(EventOutboxModel.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def requeue_outbox_events(
    session: AsyncSession,
    *,
    ids: list[str] | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[EventOutboxModel]:
    requested_ids = [str(event_id).strip() for event_id in (ids or []) if str(event_id).strip()]
    replayable_statuses = [str(status).strip() for status in (statuses or REPLAYABLE_OUTBOX_STATUSES) if str(status).strip()]
    if not replayable_statuses:
        replayable_statuses = list(REPLAYABLE_OUTBOX_STATUSES)

    statement = select(EventOutboxModel).where(
        EventOutboxModel.status.in_(replayable_statuses)
    )
    if requested_ids:
        statement = statement.where(EventOutboxModel.id.in_(requested_ids))

    result = await session.execute(
        statement
        .order_by(EventOutboxModel.created_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars().all())
    replay_requested_at = datetime.now(timezone.utc).isoformat()

    for row in rows:
        previous_status = row.status
        headers = dict(row.headers or {})
        headers["replay_previous_status"] = previous_status
        headers["replay_requested_at"] = replay_requested_at
        headers["replay_request_count"] = int(headers.get("replay_request_count", 0) or 0) + 1
        row.headers = headers
        row.status = "pending"
        row.attempt_count = 0
        row.broker_message_id = None
        row.last_error = None
        row.published_at = None

    return rows
