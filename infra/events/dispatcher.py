from __future__ import annotations

from datetime import datetime, timezone
from inspect import isawaitable

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker

from infra.events.broker import EventBroker
from infra.events.outbox import claim_pending_events


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        broker: EventBroker,
        batch_size: int = 100,
    ) -> None:
        self.session_factory = session_factory
        self.broker = broker
        self.batch_size = batch_size

    async def run_once(self) -> int:
        published = 0

        try:
            async with self.session_factory() as session:
                events = await claim_pending_events(session, limit=self.batch_size)

                for event in events:
                    try:
                        message_id = await self.broker.publish(
                            topic=event.topic,
                            payload=event.payload,
                            key=event.event_key,
                        )
                        event.status = "published"
                        event.broker_message_id = message_id
                        event.published_at = datetime.now(timezone.utc)
                        published += 1
                    except Exception as exc:
                        event.attempt_count += 1
                        if event.attempt_count >= event.max_attempts:
                            event.status = "dead_letter"
                        event.last_error = str(exc)

                await session.commit()
        finally:
            close_method = getattr(self.broker, "close", None)
            if callable(close_method):
                try:
                    close_result = close_method()
                    if isawaitable(close_result):
                        await close_result
                except Exception:
                    logger.exception("failed to close event broker cleanly")

        return published
