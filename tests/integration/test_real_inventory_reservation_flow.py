from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domains.inventory.schema import InventoryReservationItem, InventoryReservationRequest
from domains.inventory.service import InventoryService
from infra.cache.inventory_reservation import reservation_key, stock_key
from infra.core.hooks import execute_after_rollback_hooks, pop_after_commit_hooks
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel, InventoryReservationModel, ProductModel
from infra.events.topics import Topics


async def _seed_product_inventory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    available_qty: int,
) -> str:
    product_id = str(uuid4())
    async with session_factory() as session:
        product = ProductModel(
            id=product_id,
            product_code=f"TEST-{uuid4().hex[:12]}",
            product_name="Real Infra Tempered Glass",
            glass_type="Tempered",
            specification="6mm",
            base_price=Decimal("88.00"),
            unit="piece",
            is_active=True,
        )
        session.add(product)
        await session.flush()
        session.add(
            InventoryModel(
                product_id=product_id,
                available_qty=available_qty,
                reserved_qty=0,
                total_qty=available_qty,
                safety_stock=1,
                warehouse_code="WH01",
                version=1,
            )
        )
        await session.commit()
    return product_id


async def _load_persisted_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    product_id: str,
) -> tuple[InventoryModel, list[InventoryReservationModel], list[EventOutboxModel]]:
    async with session_factory() as session:
        inventory = (
            await session.execute(
                select(InventoryModel).where(InventoryModel.product_id == product_id)
            )
        ).scalar_one()
        reservations = list(
            (
                await session.execute(
                    select(InventoryReservationModel)
                    .where(InventoryReservationModel.product_id == product_id)
                    .order_by(InventoryReservationModel.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        outbox_rows = list(
            (
                await session.execute(
                    select(EventOutboxModel).order_by(EventOutboxModel.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
    return inventory, reservations, outbox_rows


@pytest.mark.asyncio
async def test_real_infra_concurrent_reservations_allow_single_winner(
    real_db_session_factory: async_sessionmaker[AsyncSession],
    real_redis_client: Redis,
    patch_real_inventory_redis,
) -> None:
    _ = patch_real_inventory_redis
    product_id = await _seed_product_inventory(real_db_session_factory, available_qty=5)
    start_event = asyncio.Event()

    async def _attempt_reservation(order_no: str):
        service = InventoryService()
        async with real_db_session_factory() as session:
            await start_event.wait()
            result = await service.reserve_stock(
                session,
                InventoryReservationRequest(
                    order_no=order_no,
                    ttl_seconds=120,
                    items=[InventoryReservationItem(product_id=product_id, quantity=4)],
                ),
            )
            if result.insufficient_items:
                await session.rollback()
                return result
            await session.commit()
            return result

    tasks = [
        asyncio.create_task(_attempt_reservation(f"GF-REAL-{uuid4().hex[:8]}")),
        asyncio.create_task(_attempt_reservation(f"GF-REAL-{uuid4().hex[:8]}")),
    ]
    start_event.set()
    first_result, second_result = await asyncio.gather(*tasks)

    results = [first_result, second_result]
    successful_results = [result for result in results if result.reservation_ids]
    failed_results = [result for result in results if result.insufficient_items]

    assert len(successful_results) == 1
    assert len(failed_results) == 1
    assert failed_results[0].insufficient_items[0].product_id == product_id
    assert failed_results[0].insufficient_items[0].available_qty == 1
    assert failed_results[0].insufficient_items[0].required_qty == 4

    inventory, reservations, outbox_rows = await _load_persisted_state(
        real_db_session_factory,
        product_id=product_id,
    )
    assert inventory.available_qty == 1
    assert inventory.reserved_qty == 4
    assert inventory.total_qty == 5
    assert inventory.version == 2
    assert len(reservations) == 1
    assert reservations[0].status == "pending"
    assert reservations[0].reserved_qty == 4
    assert len(outbox_rows) == 1
    assert outbox_rows[0].topic == Topics.INVENTORY_RESERVED

    stock_snapshot = await real_redis_client.hgetall(stock_key(product_id))
    assert stock_snapshot["available_qty"] == "1"
    assert stock_snapshot["reserved_qty"] == "4"
    assert stock_snapshot["total_qty"] == "5"

    reservation_snapshot = await real_redis_client.hgetall(reservation_key(reservations[0].id))
    assert reservation_snapshot["status"] == "pending"
    assert reservation_snapshot["quantity"] == "4"


@pytest.mark.asyncio
async def test_real_infra_rollback_restores_redis_and_db_state(
    real_db_session_factory: async_sessionmaker[AsyncSession],
    real_redis_client: Redis,
    patch_real_inventory_redis,
) -> None:
    _ = patch_real_inventory_redis
    product_id = await _seed_product_inventory(real_db_session_factory, available_qty=5)
    service = InventoryService()
    order_no = f"GF-ROLLBACK-{uuid4().hex[:8]}"

    async with real_db_session_factory() as session:
        result = await service.reserve_stock(
            session,
            InventoryReservationRequest(
                order_no=order_no,
                ttl_seconds=120,
                items=[InventoryReservationItem(product_id=product_id, quantity=3)],
            ),
        )

        assert len(result.reservation_ids) == 1
        pending_reservation_id = result.reservation_ids[0]

        stock_before_rollback = await real_redis_client.hgetall(stock_key(product_id))
        assert stock_before_rollback["available_qty"] == "2"
        assert stock_before_rollback["reserved_qty"] == "3"
        assert await real_redis_client.exists(reservation_key(pending_reservation_id)) == 1

        pop_after_commit_hooks(session)
        await session.rollback()
        await execute_after_rollback_hooks(session)

    stock_after_rollback = await real_redis_client.hgetall(stock_key(product_id))
    assert stock_after_rollback["available_qty"] == "5"
    assert stock_after_rollback["reserved_qty"] == "0"
    assert stock_after_rollback["total_qty"] == "5"
    assert await real_redis_client.exists(reservation_key(pending_reservation_id)) == 0

    inventory, reservations, outbox_rows = await _load_persisted_state(
        real_db_session_factory,
        product_id=product_id,
    )
    assert inventory.available_qty == 5
    assert inventory.reserved_qty == 0
    assert inventory.total_qty == 5
    assert inventory.version == 1
    assert reservations == []
    assert outbox_rows == []
