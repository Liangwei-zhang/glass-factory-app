from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel


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
