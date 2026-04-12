from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domains.inventory.schema import InventoryReservationItem, InventoryReservationRequest
from domains.inventory.service import InventoryService
from infra.core.hooks import pop_after_rollback_hooks
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel, InventoryReservationModel


class DummySession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class StubInventoryRepository:
    def __init__(
        self,
        *,
        inventory_rows: list[InventoryModel] | None = None,
        reservation_rows: list[InventoryReservationModel] | None = None,
        expired_rows: list[InventoryReservationModel] | None = None,
    ) -> None:
        self.inventory_rows = inventory_rows or []
        self.reservation_rows = reservation_rows or []
        self.expired_rows = expired_rows or []

    async def list_inventory_for_update(
        self, _session, product_ids: list[str]
    ) -> list[InventoryModel]:
        return [row for row in self.inventory_rows if row.product_id in product_ids]

    async def list_reservations(
        self,
        _session,
        reservation_ids: list[str],
        *,
        for_update: bool = False,
    ) -> list[InventoryReservationModel]:
        _ = for_update
        return [row for row in self.reservation_rows if row.id in reservation_ids]

    async def list_expired_pending_reservations(
        self,
        _session,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[InventoryReservationModel]:
        expired = [
            row
            for row in self.expired_rows
            if row.expires_at is not None and row.expires_at <= cutoff
        ]
        return expired[:limit]

    async def get_inventory(self, _session, product_id: str) -> InventoryModel | None:
        for row in self.inventory_rows:
            if row.product_id == product_id:
                return row
        return None


class FakeReservationStore:
    def __init__(self) -> None:
        self.reserve_calls: list[dict] = []
        self.confirm_calls: list[dict] = []
        self.release_calls: list[dict] = []
        self.restore_calls: list[dict] = []

    async def reserve(self, *, stock_snapshots, reservation_snapshots, ttl_seconds: int):
        self.reserve_calls.append(
            {
                "stock_snapshots": list(stock_snapshots),
                "reservation_snapshots": list(reservation_snapshots),
                "ttl_seconds": ttl_seconds,
            }
        )
        return []

    async def confirm(self, *, stock_snapshots, reservation_snapshots) -> None:
        self.confirm_calls.append(
            {
                "stock_snapshots": list(stock_snapshots),
                "reservation_snapshots": list(reservation_snapshots),
            }
        )

    async def release(self, *, stock_snapshots, reservation_snapshots, release_reason: str) -> None:
        self.release_calls.append(
            {
                "stock_snapshots": list(stock_snapshots),
                "reservation_snapshots": list(reservation_snapshots),
                "release_reason": release_reason,
            }
        )

    async def restore_state(
        self,
        *,
        stock_snapshots,
        reservation_snapshots,
        delete_reservation_ids=(),
    ) -> None:
        self.restore_calls.append(
            {
                "stock_snapshots": list(stock_snapshots),
                "reservation_snapshots": list(reservation_snapshots),
                "delete_reservation_ids": list(delete_reservation_ids),
            }
        )


def _build_inventory_row(
    *,
    product_id: str,
    available_qty: int,
    reserved_qty: int,
    total_qty: int,
    version: int = 1,
) -> InventoryModel:
    return InventoryModel(
        id=f"inv-{product_id}",
        product_id=product_id,
        available_qty=available_qty,
        reserved_qty=reserved_qty,
        total_qty=total_qty,
        safety_stock=0,
        warehouse_code="WH01",
        version=version,
    )


def _build_reservation_row(
    *,
    reservation_id: str,
    product_id: str,
    quantity: int,
    status: str,
    order_no: str = "GF-1001",
    expires_at: datetime | None = None,
    confirmed_at: datetime | None = None,
) -> InventoryReservationModel:
    return InventoryReservationModel(
        id=reservation_id,
        product_id=product_id,
        order_no=order_no,
        reserved_qty=quantity,
        status=status,
        expires_at=expires_at,
        confirmed_at=confirmed_at,
    )


@pytest.mark.asyncio
async def test_reserve_stock_aggregates_duplicate_product_quantities() -> None:
    session = DummySession()
    inventory_row = _build_inventory_row(
        product_id="product-1",
        available_qty=10,
        reserved_qty=0,
        total_qty=10,
    )
    repository = StubInventoryRepository(inventory_rows=[inventory_row])
    store = FakeReservationStore()
    service = InventoryService(repository=repository, reservation_store=store)

    result = await service.reserve_stock(
        session,
        InventoryReservationRequest(
            order_no="GF-1001",
            ttl_seconds=600,
            items=[
                InventoryReservationItem(product_id="product-1", quantity=3),
                InventoryReservationItem(product_id="product-1", quantity=2),
            ],
        ),
    )

    assert len(result.reservation_ids) == 1
    assert inventory_row.available_qty == 5
    assert inventory_row.reserved_qty == 5
    assert inventory_row.total_qty == 10

    reservation_rows = [row for row in session.added if isinstance(row, InventoryReservationModel)]
    assert len(reservation_rows) == 1
    assert reservation_rows[0].reserved_qty == 5

    assert len(store.reserve_calls) == 1
    assert store.reserve_calls[0]["reservation_snapshots"][0].quantity == 5
    assert any(isinstance(row, EventOutboxModel) for row in session.added)

    rollback_hooks = pop_after_rollback_hooks(session)
    assert len(rollback_hooks) == 1
    await rollback_hooks[0](session)
    assert store.restore_calls[0]["delete_reservation_ids"] == result.reservation_ids


@pytest.mark.asyncio
async def test_confirm_stock_moves_reserved_qty_into_deducted_state() -> None:
    session = DummySession()
    inventory_row = _build_inventory_row(
        product_id="product-1",
        available_qty=7,
        reserved_qty=3,
        total_qty=10,
    )
    reservation_row = _build_reservation_row(
        reservation_id="res-1",
        product_id="product-1",
        quantity=3,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    repository = StubInventoryRepository(
        inventory_rows=[inventory_row],
        reservation_rows=[reservation_row],
    )
    store = FakeReservationStore()
    service = InventoryService(repository=repository, reservation_store=store)

    changed = await service.confirm_stock(session, ["res-1"], order_id="order-1")

    assert changed == 1
    assert reservation_row.status == "confirmed"
    assert reservation_row.order_id == "order-1"
    assert reservation_row.confirmed_at is not None
    assert inventory_row.available_qty == 7
    assert inventory_row.reserved_qty == 0
    assert inventory_row.total_qty == 7
    assert len(store.confirm_calls) == 1

    rollback_hooks = pop_after_rollback_hooks(session)
    assert len(rollback_hooks) == 1
    await rollback_hooks[0](session)
    assert store.restore_calls[0]["reservation_snapshots"][0].status == "pending"


@pytest.mark.asyncio
async def test_release_stock_restores_available_qty_for_confirmed_reservation() -> None:
    session = DummySession()
    inventory_row = _build_inventory_row(
        product_id="product-1",
        available_qty=7,
        reserved_qty=0,
        total_qty=7,
    )
    reservation_row = _build_reservation_row(
        reservation_id="res-1",
        product_id="product-1",
        quantity=3,
        status="confirmed",
        confirmed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    repository = StubInventoryRepository(
        inventory_rows=[inventory_row],
        reservation_rows=[reservation_row],
    )
    store = FakeReservationStore()
    service = InventoryService(repository=repository, reservation_store=store)

    changed = await service.release_stock(
        session,
        ["res-1"],
        order_id="order-1",
        release_reason="order_cancelled",
    )

    assert changed == 1
    assert reservation_row.status == "released"
    assert reservation_row.release_reason == "order_cancelled"
    assert reservation_row.released_at is not None
    assert inventory_row.available_qty == 10
    assert inventory_row.reserved_qty == 0
    assert inventory_row.total_qty == 10
    assert len(store.release_calls) == 1
    assert store.release_calls[0]["release_reason"] == "order_cancelled"


@pytest.mark.asyncio
async def test_release_expired_reservations_uses_pending_release_flow() -> None:
    session = DummySession()
    inventory_row = _build_inventory_row(
        product_id="product-1",
        available_qty=7,
        reserved_qty=3,
        total_qty=10,
    )
    expired_row = _build_reservation_row(
        reservation_id="res-1",
        product_id="product-1",
        quantity=3,
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    repository = StubInventoryRepository(
        inventory_rows=[inventory_row],
        reservation_rows=[expired_row],
        expired_rows=[expired_row],
    )
    store = FakeReservationStore()
    service = InventoryService(repository=repository, reservation_store=store)

    changed = await service.release_expired_reservations(session, limit=10)

    assert changed == 1
    assert expired_row.status == "released"
    assert expired_row.release_reason == "reservation_expired"
    assert inventory_row.available_qty == 10
    assert inventory_row.reserved_qty == 0
    assert inventory_row.total_qty == 10
    assert len(store.release_calls) == 1
    assert store.release_calls[0]["release_reason"] == "reservation_expired"
