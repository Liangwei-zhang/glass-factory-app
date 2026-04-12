from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from domains.orders.schema import CreateOrderItem, CreateOrderRequest
from domains.orders.service import OrdersService
from infra.cache.inventory_reservation import reservation_key, stock_key
from infra.db.models.customers import CustomerModel
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel, InventoryReservationModel, ProductModel
from infra.db.models.orders import OrderModel
from infra.db.models.production import WorkOrderModel
from infra.events.topics import Topics


async def _seed_customer_product_inventory(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    available_qty: int,
) -> tuple[str, str]:
    customer_id = str(uuid4())
    product_id = str(uuid4())
    async with session_factory() as session:
        session.add(
            CustomerModel(
                id=customer_id,
                customer_code=f"CUST-REAL-{uuid4().hex[:8].upper()}",
                company_name="Real Infra Customer",
                contact_name="Alice",
                phone="13800000000",
                email="alice@example.com",
                address="Factory pickup",
                credit_limit=Decimal("100000.00"),
                credit_used=Decimal("0.00"),
                price_level="standard",
                is_active=True,
            )
        )
        product = ProductModel(
            id=product_id,
            product_code=f"REAL-ORD-{uuid4().hex[:12].upper()}",
            product_name="Real Orders Tempered Glass",
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
    return customer_id, product_id


def _build_create_order_request(
    *, customer_id: str, product_id: str, idempotency_key: str
) -> CreateOrderRequest:
    return CreateOrderRequest(
        customer_id=customer_id,
        delivery_address="Factory pickup",
        expected_delivery_date=datetime.now(timezone.utc) + timedelta(days=2),
        priority="normal",
        remark="Real infra OrdersService order",
        idempotency_key=idempotency_key,
        items=[
            CreateOrderItem(
                product_id=product_id,
                product_name="Real Orders Tempered Glass",
                glass_type="Tempered",
                specification="6mm",
                width_mm=1200,
                height_mm=800,
                quantity=3,
                unit_price=Decimal("88.00"),
                process_requirements="temper",
            )
        ],
    )


async def _load_order_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    order_id: str,
    product_id: str,
) -> tuple[
    OrderModel,
    InventoryModel,
    list[InventoryReservationModel],
    list[WorkOrderModel],
    list[EventOutboxModel],
]:
    async with session_factory() as session:
        order = (
            await session.execute(
                select(OrderModel)
                .options(selectinload(OrderModel.items))
                .where(OrderModel.id == order_id)
            )
        ).scalar_one()
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
        work_orders = list(
            (
                await session.execute(
                    select(WorkOrderModel)
                    .where(WorkOrderModel.order_id == order_id)
                    .order_by(WorkOrderModel.created_at.asc())
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
    return order, inventory, reservations, work_orders, outbox_rows


@pytest.mark.asyncio
async def test_real_infra_orders_service_create_order_persists_main_path(
    real_db_session_factory: async_sessionmaker[AsyncSession],
    real_redis_client: Redis,
    patch_real_inventory_redis,
) -> None:
    _ = patch_real_inventory_redis
    customer_id, product_id = await _seed_customer_product_inventory(
        real_db_session_factory,
        available_qty=10,
    )
    service = OrdersService()
    payload = _build_create_order_request(
        customer_id=customer_id,
        product_id=product_id,
        idempotency_key=f"real-orders-create-{uuid4().hex[:12]}",
    )

    async with real_db_session_factory() as session:
        created_order = await service.create_order(session, payload)
        await session.commit()

    persisted_order, inventory, reservations, work_orders, outbox_rows = await _load_order_state(
        real_db_session_factory,
        order_id=created_order.id,
        product_id=product_id,
    )
    assert persisted_order.id == created_order.id
    assert persisted_order.status == "pending"
    assert persisted_order.customer_id == customer_id
    assert persisted_order.total_quantity == 3
    assert len(persisted_order.items) == 1
    assert persisted_order.items[0].product_id == product_id

    assert inventory.available_qty == 7
    assert inventory.reserved_qty == 3
    assert inventory.total_qty == 10
    assert inventory.version == 2

    assert len(reservations) == 1
    assert reservations[0].id == persisted_order.reservation_ids[0]
    assert reservations[0].status == "pending"
    assert reservations[0].reserved_qty == 3
    assert reservations[0].order_no == persisted_order.order_no

    assert len(work_orders) == 1
    assert work_orders[0].order_id == persisted_order.id
    assert work_orders[0].order_item_id == persisted_order.items[0].id
    assert work_orders[0].process_step_key == "cutting"
    assert work_orders[0].status == "pending"
    assert work_orders[0].quantity == 3

    topics = [row.topic for row in outbox_rows]
    assert topics == [Topics.INVENTORY_RESERVED, Topics.ORDER_CREATED]

    stock_snapshot = await real_redis_client.hgetall(stock_key(product_id))
    assert stock_snapshot["available_qty"] == "7"
    assert stock_snapshot["reserved_qty"] == "3"
    assert stock_snapshot["total_qty"] == "10"

    reservation_snapshot = await real_redis_client.hgetall(reservation_key(reservations[0].id))
    assert reservation_snapshot["status"] == "pending"
    assert reservation_snapshot["quantity"] == "3"
    assert reservation_snapshot["order_no"] == persisted_order.order_no


@pytest.mark.asyncio
async def test_real_infra_orders_service_cancel_releases_inventory_and_reservation(
    real_db_session_factory: async_sessionmaker[AsyncSession],
    real_redis_client: Redis,
    patch_real_inventory_redis,
) -> None:
    _ = patch_real_inventory_redis
    customer_id, product_id = await _seed_customer_product_inventory(
        real_db_session_factory,
        available_qty=10,
    )
    service = OrdersService()
    payload = _build_create_order_request(
        customer_id=customer_id,
        product_id=product_id,
        idempotency_key=f"real-orders-cancel-{uuid4().hex[:12]}",
    )

    async with real_db_session_factory() as session:
        created_order = await service.create_order(session, payload)
        await session.commit()

    async with real_db_session_factory() as session:
        cancelled_order = await service.cancel_order(
            session,
            created_order.id,
            reason="customer_changed_mind",
        )
        await session.commit()

    persisted_order, inventory, reservations, work_orders, outbox_rows = await _load_order_state(
        real_db_session_factory,
        order_id=cancelled_order.id,
        product_id=product_id,
    )
    assert persisted_order.status == "cancelled"
    assert persisted_order.cancelled_reason == "customer_changed_mind"
    assert persisted_order.total_quantity == 3
    assert len(work_orders) == 1

    assert inventory.available_qty == 10
    assert inventory.reserved_qty == 0
    assert inventory.total_qty == 10
    assert inventory.version == 3

    assert len(reservations) == 1
    assert reservations[0].status == "released"
    assert reservations[0].release_reason == "order_cancelled"
    assert reservations[0].released_at is not None

    topics = [row.topic for row in outbox_rows]
    assert topics == [
        Topics.INVENTORY_RESERVED,
        Topics.ORDER_CREATED,
        Topics.INVENTORY_ROLLED_BACK,
        Topics.ORDER_CANCELLED,
    ]

    stock_snapshot = await real_redis_client.hgetall(stock_key(product_id))
    assert stock_snapshot["available_qty"] == "10"
    assert stock_snapshot["reserved_qty"] == "0"
    assert stock_snapshot["total_qty"] == "10"

    reservation_snapshot = await real_redis_client.hgetall(reservation_key(reservations[0].id))
    assert reservation_snapshot["status"] == "released"
    assert reservation_snapshot["release_reason"] == "order_cancelled"
