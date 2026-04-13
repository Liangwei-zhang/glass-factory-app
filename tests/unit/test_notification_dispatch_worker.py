from __future__ import annotations

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
        _user("cutting-1", role="operator", stage="cutting"),
    ]
    event = _event(Topics.ORDER_READY_FOR_PICKUP)

    targets = notification_dispatch_worker._resolve_target_user_ids(event, active_users)

    assert targets == ["manager-1", "office-1"]


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
