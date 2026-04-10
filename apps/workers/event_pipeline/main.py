from __future__ import annotations

from infra.db.session import build_session_factory
from infra.events.broker import build_event_broker
from infra.events.dispatcher import OutboxDispatcher


async def run_once(batch_size: int = 100) -> int:
    dispatcher = OutboxDispatcher(
        session_factory=build_session_factory(),
        broker=build_event_broker(),
        batch_size=batch_size,
    )
    return await dispatcher.run_once()
