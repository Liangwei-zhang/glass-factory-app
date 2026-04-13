from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.workers.notification_dispatch import main as notification_dispatch_worker
from infra.db.models.events import EventOutboxModel
from infra.db.models.users import UserModel
from infra.events.topics import Topics


def _user(user_id: str, *, role: str, stage: str | None = None) -> UserModel:
    return UserModel(
        id=user_id,
        username=f"user-{user_id}",
        email=f"{user_id}@example.com",
        password_hash="hash",
        display_name=f"User {user_id}",
        role=role,
        stage=stage,
        scopes=[],
        is_active=True,
    )


def _event(topic: str, payload: dict | None = None) -> EventOutboxModel:
    return EventOutboxModel(topic=topic, payload=payload or {}, status="published")


class _ScalarRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, execute_results):
        self._execute_results = list(execute_results)

    async def execute(self, _statement):
        if not self._execute_results:
            raise AssertionError("Unexpected execute call in notification dispatch worker test.")
        return _ScalarRowsResult(self._execute_results.pop(0))


def test_resolve_target_user_ids_prefers_explicit_notify_user_ids() -> None:
    active_users = [
        _user("manager-1", role="manager"),
        _user("office-1", role="operator"),
        _user("cutting-1", role="operator", stage="cutting"),
    ]
    event = _event(
        Topics.ORDER_CREATED,
        payload={"notify_user_ids": ["manager-1", "missing-user", "office-1"]},
    )

    targets = notification_dispatch_worker._resolve_target_user_ids(event, active_users)

    assert targets == ["manager-1", "office-1"]


def test_resolve_target_user_ids_internal_ops_sends_to_manager_and_office_operator() -> None:
    active_users = [
        _user("manager-1", role="manager"),
        _user("office-1", role="operator"),
        _user("finishing-1", role="operator", stage="finishing"),
    ]
    event = _event(Topics.ORDER_READY_FOR_PICKUP)

    targets = notification_dispatch_worker._resolve_target_user_ids(event, active_users)

    assert targets == ["finishing-1", "manager-1", "office-1"]


def test_resolve_target_user_ids_production_stage_event_routes_to_stage_operator() -> None:
    active_users = [
        _user("manager-1", role="manager"),
        _user("cutting-1", role="operator", stage="cutting"),
        _user("edging-1", role="operator", stage="edging"),
    ]
    event = _event(Topics.PRODUCTION_SCHEDULED, payload={"step_key": "edging"})

    targets = notification_dispatch_worker._resolve_target_user_ids(event, active_users)

    assert targets == ["edging-1", "manager-1"]


def test_resolve_target_user_ids_rework_forces_cutting_stage_target() -> None:
    active_users = [
        _user("manager-1", role="manager"),
        _user("cutting-1", role="operator", stage="cutting"),
        _user("finishing-1", role="operator", stage="finishing"),
    ]
    event = _event(Topics.PRODUCTION_REWORK_REQUESTED, payload={"step_key": "finishing"})

    targets = notification_dispatch_worker._resolve_target_user_ids(event, active_users)

    assert targets == ["cutting-1", "manager-1"]


@pytest.mark.asyncio
async def test_claim_undispatched_published_events_scans_past_already_dispatched_batches() -> None:
    now = datetime.now(timezone.utc)
    dispatched_old_1 = EventOutboxModel(
        id="evt-old-1",
        topic=Topics.ORDER_CREATED,
        payload={"order_id": "order-1"},
        headers={"notification_dispatched": True},
        status="published",
        published_at=now,
        created_at=now,
    )
    dispatched_old_2 = EventOutboxModel(
        id="evt-old-2",
        topic=Topics.ORDER_CREATED,
        payload={"order_id": "order-2"},
        headers={"notification_dispatched": True},
        status="published",
        published_at=now + timedelta(seconds=1),
        created_at=now + timedelta(seconds=1),
    )
    fresh_event = EventOutboxModel(
        id="evt-fresh-1",
        topic=Topics.ORDER_READY_FOR_PICKUP,
        payload={"order_id": "order-3"},
        headers={},
        status="published",
        published_at=now + timedelta(seconds=2),
        created_at=now + timedelta(seconds=2),
    )
    session = _FakeSession([
        [dispatched_old_1, dispatched_old_2],
        [fresh_event],
        [],
    ])

    rows = await notification_dispatch_worker._claim_undispatched_published_events(session, batch_size=2)

    assert rows == [fresh_event]
