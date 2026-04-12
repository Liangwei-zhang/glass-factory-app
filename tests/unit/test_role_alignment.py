from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.admin_api.routers import users as users_router
from domains.orders.service import OrdersService
from infra.core.errors import AppError
from infra.db.models.users import UserModel


@pytest.mark.asyncio
async def test_apply_step_action_requires_stage_for_canonical_operator() -> None:
    repository = AsyncMock()
    repository.get_order.return_value = object()
    service = OrdersService(repository=repository)

    with pytest.raises(AppError) as exc_info:
        await service.apply_step_action(
            session=AsyncMock(),
            order_id="order-1",
            step_key="cutting",
            action="start",
            actor_user_id="user-1",
            actor_role="operator",
            actor_stage=None,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Operator stage is not configured."


@pytest.mark.asyncio
async def test_update_user_preserves_stage_for_operator_role_without_stage_field() -> None:
    session = AsyncMock()
    row = UserModel(
        id="user-1",
        username="cutting",
        email="cutting@glass.local",
        display_name="Cutting Operator",
        role="operator",
        stage="cutting",
        scopes=[],
        is_active=True,
    )
    session.get.return_value = row

    payload = users_router.UpdateUserRequest(role="operator")
    result = await users_router.update_user(
        payload,
        user_id="user-1",
        session=session,
        user=SimpleNamespace(user_id="admin-1"),
    )

    assert row.stage == "cutting"
    assert result["stage"] == "cutting"


@pytest.mark.asyncio
async def test_update_user_clears_stage_when_switching_to_manager() -> None:
    session = AsyncMock()
    row = UserModel(
        id="user-1",
        username="cutting",
        email="cutting@glass.local",
        display_name="Cutting Operator",
        role="operator",
        stage="cutting",
        scopes=[],
        is_active=True,
    )
    session.get.return_value = row

    payload = users_router.UpdateUserRequest(role="manager")
    result = await users_router.update_user(
        payload,
        user_id="user-1",
        session=session,
        user=SimpleNamespace(user_id="admin-1"),
    )

    assert row.stage is None
    assert result["stage"] is None