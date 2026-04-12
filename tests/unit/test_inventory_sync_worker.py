from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest

from apps.workers.inventory_sync import main as inventory_sync_worker
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel
from infra.events.topics import Topics


class _FakeScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(
        self, inventory_rows: list[InventoryModel], existing_alert_ids: list[str] | None = None
    ) -> None:
        self.inventory_rows = inventory_rows
        self.existing_alert_ids = existing_alert_ids or []
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        query = " ".join(str(statement).lower().split())
        if "from inventory" in query:
            return _FakeScalarResult(self.inventory_rows)
        if "from event_outbox" in query:
            return _FakeScalarResult(self.existing_alert_ids)
        raise NotImplementedError(f"Unexpected statement: {statement}")

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _FakeInventoryService:
    def __init__(self, expired_release_count: int) -> None:
        self.expired_release_count = expired_release_count
        self.calls: list[int] = []

    async def release_expired_reservations(self, session, *, limit: int = 200) -> int:
        _ = session
        self.calls.append(limit)
        return self.expired_release_count


def _build_inventory_row(
    *, available_qty: int, reserved_qty: int, total_qty: int, safety_stock: int
) -> InventoryModel:
    return InventoryModel(
        id="inv-1",
        product_id="product-1",
        available_qty=available_qty,
        reserved_qty=reserved_qty,
        total_qty=total_qty,
        safety_stock=safety_stock,
        warehouse_code="WH01",
        version=1,
        updated_at=datetime.now(timezone.utc),
    )


@asynccontextmanager
async def _session_context(session: _FakeSession):
    yield session


@pytest.mark.asyncio
async def test_run_once_counts_expired_release_sync_and_low_stock_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory_row = _build_inventory_row(
        available_qty=2,
        reserved_qty=0,
        total_qty=5,
        safety_stock=3,
    )
    session = _FakeSession([inventory_row])
    fake_inventory_service = _FakeInventoryService(expired_release_count=2)

    monkeypatch.setattr(inventory_sync_worker, "InventoryService", lambda: fake_inventory_service)
    monkeypatch.setattr(
        inventory_sync_worker,
        "build_session_factory",
        lambda: (lambda: _session_context(session)),
    )

    changed = await inventory_sync_worker.run_once(batch_size=10, alert_cooldown_minutes=30)

    assert changed == 4
    assert fake_inventory_service.calls == [10]
    assert inventory_row.total_qty == 2
    assert inventory_row.version == 2
    assert session.committed is True
    outbox_rows = [row for row in session.added if isinstance(row, EventOutboxModel)]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].topic == Topics.INVENTORY_LOW_STOCK
    assert outbox_rows[0].event_key == "product-1"


@pytest.mark.asyncio
async def test_run_once_skips_duplicate_low_stock_alert_with_recent_outbox_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory_row = _build_inventory_row(
        available_qty=1,
        reserved_qty=0,
        total_qty=1,
        safety_stock=3,
    )
    session = _FakeSession([inventory_row], existing_alert_ids=["evt-1"])
    fake_inventory_service = _FakeInventoryService(expired_release_count=0)

    monkeypatch.setattr(inventory_sync_worker, "InventoryService", lambda: fake_inventory_service)
    monkeypatch.setattr(
        inventory_sync_worker,
        "build_session_factory",
        lambda: (lambda: _session_context(session)),
    )

    changed = await inventory_sync_worker.run_once(batch_size=10, alert_cooldown_minutes=30)

    assert changed == 0
    assert fake_inventory_service.calls == [10]
    assert session.committed is True
    assert session.added == []
