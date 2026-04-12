from __future__ import annotations

import pytest

from domains.orders.schema import UpdateOrderItemRequest, UpdateOrderRequest
from infra.core.errors import AppError
from infra.db.models.events import EventOutboxModel
from tests.support.order_inventory_flow import build_order_inventory_harness, make_create_order_request


@pytest.mark.asyncio
async def test_create_order_then_cancel_restores_inventory() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-create-cancel"),
    )

    assert harness.inventory_row.available_qty == 7
    assert harness.inventory_row.reserved_qty == 3
    assert len(order.reservation_ids) == 1

    cancelled_order = await harness.orders_service.cancel_order(
        harness.session,
        order.id,
        reason="customer_changed_mind",
    )

    reservation = harness.inventory_repository.reservation_rows[order.reservation_ids[0]]
    assert cancelled_order.status == "cancelled"
    assert harness.inventory_row.available_qty == 10
    assert harness.inventory_row.reserved_qty == 0
    assert reservation.status == "released"
    assert reservation.release_reason == "order_cancelled"

    topics = [row.topic for row in harness.session.added if isinstance(row, EventOutboxModel)]
    assert "inventory.stock.reserved" in topics
    assert "inventory.stock.rolled_back" in topics
    assert "orders.order.cancelled" in topics


@pytest.mark.asyncio
async def test_create_order_then_confirm_deducts_inventory() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=4, idempotency_key="integration-create-confirm"),
    )

    confirmed_order = await harness.orders_service.confirm_order(harness.session, order.id)

    reservation = harness.inventory_repository.reservation_rows[order.reservation_ids[0]]
    assert confirmed_order.status == "confirmed"
    assert harness.inventory_row.available_qty == 6
    assert harness.inventory_row.reserved_qty == 0
    assert harness.inventory_row.total_qty == 6
    assert reservation.status == "confirmed"
    assert reservation.confirmed_at is not None

    topics = [row.topic for row in harness.session.added if isinstance(row, EventOutboxModel)]
    assert "inventory.stock.reserved" in topics
    assert "inventory.stock.deducted" in topics
    assert "orders.order.confirmed" in topics


@pytest.mark.asyncio
async def test_create_order_then_mark_entered_confirms_inventory() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-create-entered"),
    )

    entered_order = await harness.orders_service.mark_entered(
        harness.session,
        order.id,
        actor_user_id="user-1",
    )

    reservation = harness.inventory_repository.reservation_rows[order.reservation_ids[0]]
    assert entered_order.status == "entered"
    assert harness.orders_repository.orders_by_id[order.id].confirmed_at is not None
    assert harness.inventory_row.available_qty == 7
    assert harness.inventory_row.reserved_qty == 0
    assert harness.inventory_row.total_qty == 7
    assert reservation.status == "confirmed"
    assert reservation.order_id == order.id

    topics = [row.topic for row in harness.session.added if isinstance(row, EventOutboxModel)]
    assert "inventory.stock.reserved" in topics
    assert "inventory.stock.deducted" in topics
    assert "orders.order.entered" in topics


@pytest.mark.asyncio
async def test_confirm_order_rejects_after_order_has_entered_production_flow() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-confirm-after-entered"),
    )
    await harness.orders_service.mark_entered(
        harness.session,
        order.id,
        actor_user_id="user-1",
    )

    with pytest.raises(AppError) as exc_info:
        await harness.orders_service.confirm_order(harness.session, order.id)

    assert exc_info.value.code == "ORDER_INVALID_TRANSITION"
    assert exc_info.value.message == "Order cannot be confirmed from current status."
    assert exc_info.value.details == {
        "order_id": order.id,
        "status": "entered",
        "current_status": "entered",
        "target_status": "confirmed",
    }


@pytest.mark.asyncio
async def test_production_step_start_requires_order_to_be_entered() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-step-before-entered"),
    )

    with pytest.raises(AppError) as exc_info:
        await harness.orders_service.apply_step_action(
            harness.session,
            order.id,
            step_key="cutting",
            action="start",
            actor_user_id="user-1",
            actor_role="manager",
        )

    assert exc_info.value.code == "ORDER_INVALID_TRANSITION"
    assert exc_info.value.message == "Order must be entered before production actions."
    assert exc_info.value.details == {
        "order_id": order.id,
        "status": "pending",
        "action": "start",
    }


@pytest.mark.asyncio
async def test_cancel_order_rejects_after_production_has_started() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-cancel-after-production-start"),
    )
    await harness.orders_service.mark_entered(
        harness.session,
        order.id,
        actor_user_id="user-1",
    )
    await harness.orders_service.apply_step_action(
        harness.session,
        order.id,
        step_key="cutting",
        action="start",
        actor_user_id="user-1",
        actor_role="manager",
    )

    with pytest.raises(AppError) as exc_info:
        await harness.orders_service.cancel_order(
            harness.session,
            order.id,
            reason="too_late",
        )

    assert exc_info.value.code == "ORDER_INVALID_TRANSITION"
    assert exc_info.value.message == "Order cannot be cancelled from current status."
    assert exc_info.value.details == {
        "order_id": order.id,
        "status": "in_production",
        "current_status": "in_production",
        "target_status": "cancelled",
    }


@pytest.mark.asyncio
async def test_approve_pickup_is_idempotent_once_order_is_ready() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-approve-pickup-idempotent"),
    )
    await harness.orders_service.mark_entered(
        harness.session,
        order.id,
        actor_user_id="user-1",
    )
    for step_key in ["cutting", "edging", "tempering", "finishing"]:
        await harness.orders_service.apply_step_action(
            harness.session,
            order.id,
            step_key=step_key,
            action="complete",
            actor_user_id="user-1",
            actor_role="manager",
        )

    first_approval = await harness.orders_service.approve_pickup(
        harness.session,
        order.id,
        actor_user_id="manager-1",
    )
    version_after_first_approval = harness.orders_repository.orders_by_id[order.id].version
    approval_topic_count = sum(
        1
        for row in harness.session.added
        if isinstance(row, EventOutboxModel) and row.topic == "orders.order.ready_for_pickup"
    )

    second_approval = await harness.orders_service.approve_pickup(
        harness.session,
        order.id,
        actor_user_id="manager-2",
    )

    assert first_approval.status == "ready_for_pickup"
    assert second_approval.status == "ready_for_pickup"
    assert harness.orders_repository.orders_by_id[order.id].version == version_after_first_approval
    assert sum(
        1
        for row in harness.session.added
        if isinstance(row, EventOutboxModel) and row.topic == "orders.order.ready_for_pickup"
    ) == approval_topic_count


@pytest.mark.asyncio
async def test_update_order_quantity_rebuilds_pending_reservation() -> None:
    harness = build_order_inventory_harness(available_qty=10)

    order = await harness.orders_service.create_order(
        harness.session,
        make_create_order_request(quantity=3, idempotency_key="integration-update-order"),
    )
    original_reservation_id = order.reservation_ids[0]

    updated_order = await harness.orders_service.update_order(
        harness.session,
        order.id,
        UpdateOrderRequest(
            items=[
                UpdateOrderItemRequest(
                    id=order.items[0].id,
                    quantity=5,
                )
            ]
        ),
        actor_user_id="user-1",
    )

    replacement_reservation_id = updated_order.reservation_ids[0]
    original_reservation = harness.inventory_repository.reservation_rows[original_reservation_id]
    replacement_reservation = harness.inventory_repository.reservation_rows[replacement_reservation_id]

    assert replacement_reservation_id != original_reservation_id
    assert updated_order.total_quantity == 5
    assert updated_order.items[0].quantity == 5
    assert harness.inventory_row.available_qty == 5
    assert harness.inventory_row.reserved_qty == 5
    assert harness.inventory_row.total_qty == 10
    assert original_reservation.status == "released"
    assert original_reservation.release_reason == "order_updated"
    assert replacement_reservation.status == "pending"
    assert replacement_reservation.reserved_qty == 5
    assert harness.session.work_orders[0].quantity == 5

    topics = [row.topic for row in harness.session.added if isinstance(row, EventOutboxModel)]
    assert "inventory.stock.reserved" in topics
    assert "inventory.stock.rolled_back" in topics
    assert "ops.audit.logged" in topics


@pytest.mark.asyncio
async def test_duplicate_create_order_by_payload_idempotency_returns_existing_order_without_extra_reserve() -> None:
    harness = build_order_inventory_harness(available_qty=10)
    payload = make_create_order_request(quantity=3, idempotency_key="integration-duplicate-create")

    first_order = await harness.orders_service.create_order(harness.session, payload)
    second_order = await harness.orders_service.create_order(harness.session, payload)

    assert first_order.id == second_order.id
    assert len(harness.orders_repository.orders_by_id) == 1
    assert len(harness.inventory_repository.reservation_rows) == 1
    assert harness.inventory_row.available_qty == 7
    assert harness.inventory_row.reserved_qty == 3