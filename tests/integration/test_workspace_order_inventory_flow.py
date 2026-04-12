from __future__ import annotations

from types import SimpleNamespace

import pytest

from domains.workspace import orders_support as workspace_orders
from tests.support.order_inventory_flow import (
    build_order_inventory_harness,
    serialize_test_order,
)


def _patch_workspace_orders(monkeypatch: pytest.MonkeyPatch, harness) -> None:
    async def fake_ensure_product_inventory(_session, glass_type: str, thickness: str, quantity: int):
        _ = (glass_type, thickness, quantity)
        return SimpleNamespace(id="product-1", product_name="Tempered Glass Panel")

    async def fake_serialize_workspace_order(_session, order_id: str, *, include_detail: bool = True):
        _ = include_detail
        return serialize_test_order(harness.orders_repository.orders_by_id[order_id])

    async def fake_get_order_model(_session, order_id: str, *, include_items: bool = True):
        _ = include_items
        return harness.orders_repository.orders_by_id[order_id]

    monkeypatch.setattr(workspace_orders, "orders_service", harness.orders_service)
    monkeypatch.setattr(workspace_orders.ui_support, "ensure_product_inventory", fake_ensure_product_inventory)
    monkeypatch.setattr(workspace_orders, "serialize_workspace_order", fake_serialize_workspace_order)
    monkeypatch.setattr(workspace_orders, "get_order_model", fake_get_order_model)


@pytest.mark.asyncio
async def test_workspace_create_then_entered_confirms_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_orders(monkeypatch, harness)

    created = await workspace_orders.create_workspace_order(
        harness.session,
        customer_id=harness.customer.id,
        glass_type="Tempered",
        thickness="6mm",
        quantity=3,
        priority="normal",
        estimated_completion_date="2026-04-12",
        special_instructions="Workspace integration order",
        drawing=None,
        idempotency_key="workspace-integration-entered",
    )

    order_id = created["order"]["id"]
    assert harness.inventory_row.available_qty == 7
    assert harness.inventory_row.reserved_qty == 3

    entered = await workspace_orders.mark_workspace_order_entered(
        harness.session,
        order_id=order_id,
        actor_user_id="user-1",
    )

    reservation = harness.inventory_repository.reservation_rows[
        harness.orders_repository.orders_by_id[order_id].reservation_ids[0]
    ]
    assert entered["order"]["status"] == "entered"
    assert harness.inventory_row.available_qty == 7
    assert harness.inventory_row.reserved_qty == 0
    assert harness.inventory_row.total_qty == 7
    assert reservation.status == "confirmed"
    assert reservation.order_id == order_id


@pytest.mark.asyncio
async def test_workspace_update_quantity_rebuilds_pending_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_orders(monkeypatch, harness)

    created = await workspace_orders.create_workspace_order(
        harness.session,
        customer_id=harness.customer.id,
        glass_type="Tempered",
        thickness="6mm",
        quantity=3,
        priority="normal",
        estimated_completion_date="2026-04-12",
        special_instructions="Workspace integration order",
        drawing=None,
        idempotency_key="workspace-integration-update",
    )

    order_id = created["order"]["id"]
    original_reservation_id = harness.orders_repository.orders_by_id[order_id].reservation_ids[0]

    updated = await workspace_orders.update_workspace_order(
        harness.session,
        order_id=order_id,
        glass_type=None,
        thickness=None,
        quantity=5,
        priority=None,
        estimated_completion_date=None,
        special_instructions=None,
        drawing=None,
        actor_user_id="user-1",
    )

    replacement_reservation_id = harness.orders_repository.orders_by_id[order_id].reservation_ids[0]
    original_reservation = harness.inventory_repository.reservation_rows[original_reservation_id]
    replacement_reservation = harness.inventory_repository.reservation_rows[replacement_reservation_id]

    assert replacement_reservation_id != original_reservation_id
    assert updated["order"]["totalQuantity"] == 5
    assert updated["order"]["items"][0]["quantity"] == 5
    assert harness.inventory_row.available_qty == 5
    assert harness.inventory_row.reserved_qty == 5
    assert original_reservation.status == "released"
    assert original_reservation.release_reason == "order_updated"
    assert replacement_reservation.status == "pending"
    assert replacement_reservation.reserved_qty == 5
    assert harness.session.work_orders[0].quantity == 5
