from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import count
from uuid import uuid4

from sqlalchemy import Select

from domains.inventory.service import InventoryService
from domains.orders.schema import CreateOrderItem, CreateOrderRequest
from domains.orders.service import OrdersService
from infra.db.models.customers import CustomerModel
from infra.db.models.finance import ReceivableModel
from infra.db.models.inventory import InventoryModel, InventoryReservationModel
from infra.db.models.logistics import ShipmentModel
from infra.db.models.orders import OrderItemModel, OrderModel
from infra.db.models.production import WorkOrderModel
from infra.db.models.settings import EmailLogModel, NotificationTemplateModel
from infra.db.models.users import UserModel
from infra.security.auth import AuthUser


class RecordingSession:
    def __init__(
        self,
        inventory_repository: MemoryInventoryRepository,
        *,
        orders_repository: MemoryOrdersRepository | None = None,
        customers: list[CustomerModel] | None = None,
        users: list[UserModel] | None = None,
        notification_templates: list[NotificationTemplateModel] | None = None,
        receivables: list[ReceivableModel] | None = None,
        shipments: list[ShipmentModel] | None = None,
    ) -> None:
        self.inventory_repository = inventory_repository
        self.orders_repository = orders_repository
        self.added: list[object] = []
        self.work_orders: list[WorkOrderModel] = []
        self.email_logs: list[EmailLogModel] = []
        self.receivables: list[ReceivableModel] = list(receivables or [])
        self.customers_by_id = {row.id: row for row in customers or []}
        self.users_by_id = {row.id: row for row in users or []}
        self.notification_templates_by_key = {
            row.template_key: row for row in notification_templates or []
        }
        self.shipments: list[ShipmentModel] = list(shipments or [])

    def add(self, obj: object) -> None:
        now = datetime.now(timezone.utc)
        self.added.append(obj)
        if isinstance(obj, InventoryReservationModel):
            self.inventory_repository.store_reservation(obj)
        if isinstance(obj, WorkOrderModel):
            self.work_orders.append(obj)
        if isinstance(obj, NotificationTemplateModel):
            self.notification_templates_by_key[obj.template_key] = obj
        if isinstance(obj, EmailLogModel):
            self.email_logs.append(obj)
        if isinstance(obj, ReceivableModel):
            if obj.id is None:
                obj.id = str(uuid4())
            if obj.created_at is None:
                obj.created_at = now
            if obj.updated_at is None:
                obj.updated_at = now
            self.receivables.append(obj)
        if isinstance(obj, ShipmentModel):
            if obj.id is None:
                obj.id = str(uuid4())
            if obj.created_at is None:
                obj.created_at = now
            if obj.updated_at is None:
                obj.updated_at = now
            self.shipments.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None

    async def get(self, model, obj_id: str):
        if model is CustomerModel:
            return self.customers_by_id.get(obj_id)
        if model is UserModel:
            return self.users_by_id.get(obj_id)
        if model is OrderModel and self.orders_repository is not None:
            return self.orders_repository.orders_by_id.get(obj_id)
        if model is ShipmentModel:
            return next((row for row in self.shipments if row.id == obj_id), None)
        if model is ReceivableModel:
            return next((row for row in self.receivables if row.id == obj_id), None)
        return None

    async def execute(self, statement: Select):
        entity = None
        if getattr(statement, "column_descriptions", None):
            entity = statement.column_descriptions[0].get("entity")

        if entity is WorkOrderModel:
            return _ScalarResult(self.work_orders)
        if entity is OrderModel and self.orders_repository is not None:
            return _ScalarResult(list(self.orders_repository.orders_by_id.values()))
        if entity is CustomerModel:
            return _ScalarResult(list(self.customers_by_id.values()))
        if entity is UserModel:
            return _ScalarResult(list(self.users_by_id.values()))
        if entity is NotificationTemplateModel:
            return _ScalarResult(list(self.notification_templates_by_key.values()))
        if entity is ReceivableModel:
            rows = sorted(self.receivables, key=lambda row: row.created_at, reverse=True)
            return _ScalarResult(rows)
        if entity is ShipmentModel:
            rows = sorted(self.shipments, key=lambda row: row.created_at, reverse=True)
            return _ScalarResult(rows)

        raise NotImplementedError(f"Unsupported statement in test harness: {statement}")


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class MemoryInventoryRepository:
    def __init__(self, inventory_rows: list[InventoryModel] | None = None) -> None:
        self.inventory_rows = {row.product_id: row for row in inventory_rows or []}
        self.reservation_rows: dict[str, InventoryReservationModel] = {}

    def store_reservation(self, row: InventoryReservationModel) -> None:
        self.reservation_rows[row.id] = row

    async def list_inventory_for_update(
        self, _session, product_ids: list[str]
    ) -> list[InventoryModel]:
        return [
            self.inventory_rows[product_id]
            for product_id in product_ids
            if product_id in self.inventory_rows
        ]

    async def list_reservations(
        self,
        _session,
        reservation_ids: list[str],
        *,
        for_update: bool = False,
    ) -> list[InventoryReservationModel]:
        _ = for_update
        return [
            self.reservation_rows[reservation_id]
            for reservation_id in reservation_ids
            if reservation_id in self.reservation_rows
        ]

    async def list_expired_pending_reservations(
        self,
        _session,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[InventoryReservationModel]:
        rows = [
            row
            for row in self.reservation_rows.values()
            if row.status == "pending" and row.expires_at is not None and row.expires_at <= cutoff
        ]
        rows.sort(key=lambda row: (row.expires_at or cutoff, row.created_at or cutoff))
        return rows[:limit]

    async def get_inventory(self, _session, product_id: str) -> InventoryModel | None:
        return self.inventory_rows.get(product_id)


class MemoryOrdersRepository:
    def __init__(self) -> None:
        self.orders_by_id: dict[str, OrderModel] = {}
        self.orders_by_idempotency_key: dict[str, OrderModel] = {}

    async def get_by_idempotency_key(self, _session, idempotency_key: str) -> OrderModel | None:
        return self.orders_by_idempotency_key.get(idempotency_key)

    async def create_order(
        self,
        session,
        order_no: str,
        payload: CreateOrderRequest,
        reservation_ids: list[str],
    ) -> OrderModel:
        _ = session
        now = datetime.now(timezone.utc)
        order = OrderModel(
            id=str(uuid4()),
            order_no=order_no,
            customer_id=payload.customer_id,
            status="pending",
            priority=payload.priority,
            total_amount=Decimal("0"),
            total_quantity=0,
            total_area_sqm=Decimal("0"),
            delivery_address=payload.delivery_address,
            expected_delivery_date=payload.expected_delivery_date,
            reservation_ids=reservation_ids,
            remark=payload.remark,
            idempotency_key=payload.idempotency_key,
            version=1,
            created_at=now,
            updated_at=now,
        )

        items: list[OrderItemModel] = []
        total_amount = Decimal("0")
        total_quantity = 0
        total_area_sqm = Decimal("0")
        for item in payload.items:
            area_sqm = (Decimal(item.width_mm) * Decimal(item.height_mm)) / Decimal("1000000")
            subtotal = item.unit_price * item.quantity
            order_item = OrderItemModel(
                id=str(uuid4()),
                order_id=order.id,
                product_id=item.product_id,
                product_name=item.product_name,
                glass_type=item.glass_type,
                specification=item.specification,
                width_mm=item.width_mm,
                height_mm=item.height_mm,
                area_sqm=area_sqm,
                quantity=item.quantity,
                unit_price=item.unit_price,
                subtotal=subtotal,
                process_requirements=item.process_requirements,
                created_at=now,
            )
            items.append(order_item)
            total_amount += subtotal
            total_quantity += item.quantity
            total_area_sqm += area_sqm * item.quantity

        order.items = items
        order.total_amount = total_amount
        order.total_quantity = total_quantity
        order.total_area_sqm = total_area_sqm

        self.orders_by_id[order.id] = order
        if payload.idempotency_key:
            self.orders_by_idempotency_key[payload.idempotency_key] = order
        return order

    async def get_order(self, _session, order_id: str) -> OrderModel | None:
        return self.orders_by_id.get(order_id)

    async def list_orders(self, _session, limit: int = 50) -> list[OrderModel]:
        rows = list(self.orders_by_id.values())
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[:limit]

    async def update_order_status(
        self,
        _session,
        order_id: str,
        status: str,
        confirmed_at: datetime | None = None,
        pickup_approved_at: datetime | None = None,
        pickup_approved_by: str | None = None,
        picked_up_at: datetime | None = None,
        picked_up_by: str | None = None,
        pickup_signer_name: str | None = None,
        pickup_signature_key: str | None = None,
        drawing_object_key: str | None = None,
        drawing_original_name: str | None = None,
        cancelled_at: datetime | None = None,
        cancelled_reason: str | None = None,
    ) -> OrderModel | None:
        row = self.orders_by_id.get(order_id)
        if row is None:
            return None

        row.status = status
        if confirmed_at is not None:
            row.confirmed_at = confirmed_at
        if pickup_approved_at is not None:
            row.pickup_approved_at = pickup_approved_at
        if pickup_approved_by is not None:
            row.pickup_approved_by = pickup_approved_by
        if picked_up_at is not None:
            row.picked_up_at = picked_up_at
        if picked_up_by is not None:
            row.picked_up_by = picked_up_by
        if pickup_signer_name is not None:
            row.pickup_signer_name = pickup_signer_name
        if pickup_signature_key is not None:
            row.pickup_signature_key = pickup_signature_key
        if drawing_object_key is not None:
            row.drawing_object_key = drawing_object_key
        if drawing_original_name is not None:
            row.drawing_original_name = drawing_original_name
        if cancelled_at is not None:
            row.cancelled_at = cancelled_at
        if cancelled_reason is not None:
            row.cancelled_reason = cancelled_reason
        row.updated_at = datetime.now(timezone.utc)
        row.version += 1
        return row


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


class StaticCustomersService:
    async def check_credit(self, **_kwargs):
        return None


class FixedOrderIdGenerator:
    def __init__(self, prefix: str = "GF") -> None:
        self.prefix = prefix
        self.counter = count(1001)

    async def generate(self, prefix: str = "GF") -> str:
        resolved_prefix = prefix or self.prefix
        return f"{resolved_prefix}-{next(self.counter)}"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        _ = ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.values:
                removed += 1
                del self.values[key]
        return removed

    async def expire(self, key: str, seconds: int) -> bool:
        _ = seconds
        return key in self.values


@dataclass(slots=True)
class OrderInventoryHarness:
    session: RecordingSession
    orders_service: OrdersService
    inventory_service: InventoryService
    orders_repository: MemoryOrdersRepository
    inventory_repository: MemoryInventoryRepository
    reservation_store: FakeReservationStore
    redis: FakeRedis
    inventory_row: InventoryModel
    customer: CustomerModel
    user: UserModel


def build_order_inventory_harness(*, available_qty: int = 10) -> OrderInventoryHarness:
    now = datetime.now(timezone.utc)
    inventory_row = InventoryModel(
        id="inv-product-1",
        product_id="product-1",
        available_qty=available_qty,
        reserved_qty=0,
        total_qty=available_qty,
        safety_stock=1,
        warehouse_code="WH01",
        version=1,
        updated_at=now,
    )
    customer = CustomerModel(
        id="cust-1",
        customer_code="CUST-TEST-0001",
        company_name="Integration Customer",
        contact_name="Alice",
        phone="13800000000",
        email="alice@example.com",
        address="Factory pickup",
        credit_limit=Decimal("100000.00"),
        credit_used=Decimal("0"),
        price_level="standard",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    user = UserModel(
        id="user-1",
        username="customer-demo",
        email="customer@example.com",
        customer_id=customer.id,
        password_hash="customer123",
        display_name="Customer Demo",
        role="customer",
        stage=None,
        scopes=[],
        is_active=True,
    )
    inventory_repository = MemoryInventoryRepository([inventory_row])
    reservation_store = FakeReservationStore()
    inventory_service = InventoryService(
        repository=inventory_repository,
        reservation_store=reservation_store,
    )
    orders_repository = MemoryOrdersRepository()
    orders_service = OrdersService(
        repository=orders_repository,
        inventory_service=inventory_service,
        id_generator=FixedOrderIdGenerator(),
        customers_service=StaticCustomersService(),
    )
    session = RecordingSession(
        inventory_repository,
        orders_repository=orders_repository,
        customers=[customer],
        users=[user],
    )
    return OrderInventoryHarness(
        session=session,
        orders_service=orders_service,
        inventory_service=inventory_service,
        orders_repository=orders_repository,
        inventory_repository=inventory_repository,
        reservation_store=reservation_store,
        redis=FakeRedis(),
        inventory_row=inventory_row,
        customer=customer,
        user=user,
    )


def make_create_order_request(
    *, quantity: int = 3, idempotency_key: str | None = None
) -> CreateOrderRequest:
    return CreateOrderRequest(
        customer_id="cust-1",
        delivery_address="Factory pickup",
        expected_delivery_date=datetime.now(timezone.utc) + timedelta(days=2),
        priority="normal",
        remark="Integration test order",
        idempotency_key=idempotency_key,
        items=[
            CreateOrderItem(
                product_id="product-1",
                product_name="Tempered Glass Panel",
                glass_type="Tempered",
                specification="6mm",
                width_mm=1200,
                height_mm=800,
                quantity=quantity,
                unit_price=Decimal("88.00"),
                process_requirements="temper",
            )
        ],
    )


def make_auth_user(
    *,
    role: str = "operator",
    scopes: list[str] | None = None,
    stage: str | None = None,
    customer_id: str | None = None,
) -> AuthUser:
    return AuthUser(
        sub="user-1",
        role=role,
        scopes=scopes or ["orders:read", "orders:write"],
        stage=stage,
        cid=customer_id,
        sid="session-1",
    )


def serialize_test_order(order: OrderModel) -> dict:
    return {
        "id": order.id,
        "orderNo": order.order_no,
        "status": order.status,
        "totalQuantity": order.total_quantity,
        "reservationIds": list(order.reservation_ids),
        "items": [
            {
                "id": item.id,
                "productId": item.product_id,
                "quantity": item.quantity,
                "glassType": item.glass_type,
                "specification": item.specification,
            }
            for item in order.items
        ],
    }
