from __future__ import annotations

from datetime import datetime, timezone

import pytest

from infra.db.models.events import EventOutboxModel
from infra.events.outbox import requeue_outbox_events


class _ScalarRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.execute_calls = 0

    async def execute(self, _statement):
        self.execute_calls += 1
        return _ScalarRowsResult(self._rows)


@pytest.mark.asyncio
async def test_requeue_outbox_events_resets_retry_state() -> None:
    now = datetime.now(timezone.utc)
    event = EventOutboxModel(
        id="evt-1",
        topic="orders.created",
        payload={"order_id": "order-1"},
        headers={"replay_request_count": 1},
        status="dead_letter",
        attempt_count=3,
        max_attempts=3,
        broker_message_id="broker-1",
        last_error="KafkaConnectionError",
        occurred_at=now,
        published_at=now,
        created_at=now,
    )
    session = _FakeSession([event])

    rows = await requeue_outbox_events(session, statuses=["dead_letter"], limit=10)

    assert rows == [event]
    assert session.execute_calls == 1
    assert event.status == "pending"
    assert event.attempt_count == 0
    assert event.broker_message_id is None
    assert event.last_error is None
    assert event.published_at is None
    assert event.headers["replay_previous_status"] == "dead_letter"
    assert event.headers["replay_request_count"] == 2
    assert "replay_requested_at" in event.headers


@pytest.mark.asyncio
async def test_requeue_outbox_events_returns_empty_when_no_rows_match() -> None:
    session = _FakeSession([])

    rows = await requeue_outbox_events(session, ids=["evt-missing"], statuses=["dead_letter"], limit=5)

    assert rows == []
    assert session.execute_calls == 1
