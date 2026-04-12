from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.customers import CustomerModel
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel, ProductModel
from infra.db.models.notifications import NotificationModel
from infra.db.models.orders import OrderModel
from infra.db.models.production import QualityCheckModel, WorkOrderModel
from infra.db.models.settings import GlassTypeModel

DEFAULT_GLASS_TYPES = [
    "Clear",
    "Rain",
    "Pinhead",
    "Grey",
    "Frosted",
]
DEFAULT_THICKNESS_OPTIONS = ["4mm", "5mm", "6mm", "8mm", "10mm", "12mm"]
DEFAULT_PRIORITIES = [
    {"value": "normal", "label": "普通"},
    {"value": "rush", "label": "加急"},
    {"value": "rework", "label": "返工"},
    {"value": "hold", "label": "Hold"},
]
DEFAULT_ORDER_STATUSES = [
    {"value": "received", "label": "已接单"},
    {"value": "entered", "label": "已录入系统"},
    {"value": "in_production", "label": "生产中"},
    {"value": "completed", "label": "已完成"},
    {"value": "shipping", "label": "配送中"},
    {"value": "delivered", "label": "已送达"},
    {"value": "ready_for_pickup", "label": "可取货"},
    {"value": "picked_up", "label": "已取货"},
    {"value": "cancelled", "label": "已取消"},
]
PRODUCTION_STEPS = [
    {"key": "cutting", "label": "切玻璃", "workerLabel": "切玻璃工人"},
    {"key": "edging", "label": "开切口", "workerLabel": "开切口工人"},
    {"key": "tempering", "label": "钢化", "workerLabel": "钢化工人"},
    {"key": "finishing", "label": "完成钢化", "workerLabel": "完成钢化处工人"},
]
STEP_LABELS = {step["key"]: step["label"] for step in PRODUCTION_STEPS}
STEP_STATUS_LABELS = {
    "pending": "待处理",
    "in_progress": "进行中",
    "completed": "已完成",
}
STATUS_LABELS = {
    "received": "已接单",
    "entered": "已录入系统",
    "in_production": "生产中",
    "completed": "已完成",
    "shipping": "配送中",
    "delivered": "已送达",
    "ready_for_pickup": "可取货",
    "picked_up": "已取货",
    "cancelled": "已取消",
}
PRIORITY_LABELS = {
    "normal": "普通",
    "rush": "加急",
    "rework": "返工",
    "hold": "Hold",
}
ACTIVE_ORDER_STATUSES = {
    "pending",
    "confirmed",
    "entered",
    "in_production",
    "completed",
    "shipping",
    "ready_for_pickup",
}
AUTO_STOCK_TARGET_AVAILABLE_QTY = 1000
AUTO_STOCK_REFILL_THRESHOLD_QTY = 250


def build_order_asset_url(route_prefix: str, order_id: str, asset: str) -> str:
    normalized_prefix = route_prefix.rstrip("/") or "/api"
    normalized_asset = asset.lstrip("/")
    return f"{normalized_prefix}/orders/{order_id}/{normalized_asset}"


def to_ui_status(status: str) -> str:
    if status in {"pending", "confirmed"}:
        return "received"
    if status in {
        "entered",
        "in_production",
        "completed",
        "shipping",
        "delivered",
        "ready_for_pickup",
        "picked_up",
        "cancelled",
    }:
        return status
    return "received"


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def priority_label(priority: str) -> str:
    return PRIORITY_LABELS.get(priority, priority)


def step_status_label(status: str) -> str:
    return STEP_STATUS_LABELS.get(status, status)


def parse_date_input(value: str | None) -> datetime:
    if value:
        text = value.strip()
        if text:
            if len(text) == 10:
                return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc) + timedelta(days=2)


def format_piece_summary(piece_numbers: list[int]) -> str:
    normalized = sorted({piece for piece in piece_numbers if piece > 0})
    if not normalized:
        return ""
    return "、".join(f"第 {piece} 片" for piece in normalized)


def serialize_customer(
    customer: Any,
    *,
    total_orders: int = 0,
    active_orders: int = 0,
    last_order_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": getattr(customer, "id"),
        "companyName": getattr(customer, "company_name"),
        "contactName": getattr(customer, "contact_name", None),
        "phone": getattr(customer, "phone", None),
        "email": getattr(customer, "email", None),
        "notes": getattr(customer, "address", None) or "",
        "totalOrders": total_orders,
        "activeOrders": active_orders,
        "hasActiveOrders": active_orders > 0,
        "lastOrderAt": last_order_at,
        "createdAt": getattr(customer, "created_at", None),
        "updatedAt": getattr(customer, "updated_at", None),
    }


async def ensure_default_glass_types(
    session: AsyncSession,
    actor_user_id: str | None = None,
) -> None:
    count = await session.scalar(select(func.count(GlassTypeModel.id)))
    if int(count or 0) > 0:
        return

    now = datetime.now(timezone.utc)
    for index, name in enumerate(DEFAULT_GLASS_TYPES):
        session.add(
            GlassTypeModel(
                name=name,
                is_active=True,
                sort_order=index,
                updated_at=now,
                updated_by=actor_user_id,
            )
        )
    await session.flush()


async def ensure_product_inventory(
    session: AsyncSession,
    glass_type: str,
    thickness: str,
    required_quantity: int,
) -> ProductModel:
    normalized_glass_type = glass_type.strip() or "Clear"
    normalized_thickness = thickness.strip() or "6mm"
    code = f"GLASS-{normalized_glass_type}-{normalized_thickness}".upper().replace(" ", "-")

    product_result = await session.execute(
        select(ProductModel).where(ProductModel.product_code == code)
    )
    product = product_result.scalar_one_or_none()
    if product is None:
        product = ProductModel(
            product_code=code,
            product_name=f"{normalized_glass_type} {normalized_thickness}",
            glass_type=normalized_glass_type,
            specification=normalized_thickness,
            base_price=Decimal("1.00"),
            unit="piece",
            is_active=True,
        )
        session.add(product)
        await session.flush()

    inventory_result = await session.execute(
        select(InventoryModel).where(InventoryModel.product_id == product.id)
    )
    inventory = inventory_result.scalar_one_or_none()
    target_available = max(required_quantity * 2, AUTO_STOCK_TARGET_AVAILABLE_QTY)
    refill_threshold = max(required_quantity, AUTO_STOCK_REFILL_THRESHOLD_QTY)
    if inventory is None:
        inventory = InventoryModel(
            product_id=product.id,
            available_qty=target_available,
            reserved_qty=0,
            total_qty=target_available,
            safety_stock=20,
            warehouse_code="WH01",
            version=1,
        )
        session.add(inventory)
    elif inventory.available_qty < refill_threshold:
        inventory.available_qty = target_available
        inventory.total_qty = inventory.available_qty + inventory.reserved_qty
        inventory.version += 1

    await session.flush()
    return product


async def serialize_notifications(
    session: AsyncSession,
    user_id: str,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(NotificationModel)
        .where(NotificationModel.user_id == user_id)
        .order_by(NotificationModel.is_read.asc(), NotificationModel.created_at.desc())
        .limit(100)
    )
    rows = list(result.scalars().all())

    order_map: dict[str, str] = {}
    order_ids = [row.order_id for row in rows if row.order_id]
    if order_ids:
        order_result = await session.execute(
            select(OrderModel.id, OrderModel.order_no).where(OrderModel.id.in_(order_ids))
        )
        order_map = {row_id: order_no for row_id, order_no in order_result.all()}

    return [
        {
            "id": row.id,
            "orderId": row.order_id,
            "orderNo": order_map.get(row.order_id or ""),
            "title": row.title,
            "message": row.message,
            "severity": row.severity,
            "isRead": bool(row.is_read),
            "createdAt": row.created_at,
        }
        for row in rows
    ]


async def serialize_customers(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(select(CustomerModel).order_by(CustomerModel.updated_at.desc()))
    customers = list(result.scalars().all())

    order_stats_result = await session.execute(
        select(OrderModel.customer_id, OrderModel.status, OrderModel.created_at)
    )
    customer_stats: dict[str, dict[str, Any]] = {}
    for customer_id, status, created_at in order_stats_result.all():
        stats = customer_stats.setdefault(
            customer_id,
            {
                "total_orders": 0,
                "active_orders": 0,
                "last_order_at": None,
            },
        )
        stats["total_orders"] += 1
        if status in ACTIVE_ORDER_STATUSES:
            stats["active_orders"] += 1
        if stats["last_order_at"] is None or created_at > stats["last_order_at"]:
            stats["last_order_at"] = created_at

    rows: list[dict[str, Any]] = []
    for customer in customers:
        stats = customer_stats.get(customer.id, {})
        rows.append(
            serialize_customer(
                customer,
                total_orders=int(stats.get("total_orders") or 0),
                active_orders=int(stats.get("active_orders") or 0),
                last_order_at=stats.get("last_order_at"),
            )
        )

    return rows


async def _load_order_serialization_dependencies(
    session: AsyncSession,
    orders: list[OrderModel],
) -> tuple[
    dict[str, CustomerModel],
    dict[str, list[WorkOrderModel]],
    dict[str, list[QualityCheckModel]],
]:
    if not orders:
        return {}, {}, {}

    customer_ids = sorted({order.customer_id for order in orders if order.customer_id})
    customer_map: dict[str, CustomerModel] = {}
    if customer_ids:
        customer_result = await session.execute(
            select(CustomerModel).where(CustomerModel.id.in_(customer_ids))
        )
        customer_map = {row.id: row for row in customer_result.scalars().all()}

    order_ids = [order.id for order in orders]
    work_order_result = await session.execute(
        select(WorkOrderModel)
        .where(WorkOrderModel.order_id.in_(order_ids))
        .order_by(WorkOrderModel.created_at.asc())
    )
    work_orders_by_order_id: dict[str, list[WorkOrderModel]] = defaultdict(list)
    work_order_ids: list[str] = []
    work_order_to_order_id: dict[str, str] = {}
    for row in work_order_result.scalars().all():
        work_orders_by_order_id[row.order_id].append(row)
        work_order_ids.append(row.id)
        work_order_to_order_id[row.id] = row.order_id

    quality_checks_by_order_id: dict[str, list[QualityCheckModel]] = defaultdict(list)
    if work_order_ids:
        quality_result = await session.execute(
            select(QualityCheckModel)
            .where(QualityCheckModel.work_order_id.in_(work_order_ids))
            .order_by(QualityCheckModel.checked_at.desc())
        )
        for row in quality_result.scalars().all():
            order_id = work_order_to_order_id.get(row.work_order_id)
            if order_id is not None:
                quality_checks_by_order_id[order_id].append(row)

    return customer_map, dict(work_orders_by_order_id), dict(quality_checks_by_order_id)


async def serialize_orders(
    session: AsyncSession,
    orders: list[OrderModel],
    *,
    include_detail: bool = False,
    route_prefix: str = "/api",
) -> list[dict[str, Any]]:
    if not orders:
        return []

    customer_map, work_orders_by_order_id, quality_checks_by_order_id = (
        await _load_order_serialization_dependencies(session, orders)
    )
    payloads: list[dict[str, Any]] = []
    for order in orders:
        payloads.append(
            await serialize_order(
                session,
                order,
                include_detail=include_detail,
                route_prefix=route_prefix,
                customer=customer_map.get(order.customer_id),
                work_orders=work_orders_by_order_id.get(order.id, []),
                quality_checks=quality_checks_by_order_id.get(order.id, []),
            )
        )
    return payloads


async def serialize_rework_requests(
    work_orders: list[WorkOrderModel],
    quality_checks: list[QualityCheckModel],
) -> list[dict[str, Any]]:
    work_order_ids = {row.id for row in work_orders}
    cutting_unread = any(
        row.process_step_key == "cutting" and bool(row.rework_unread) for row in work_orders
    )
    rows: list[dict[str, Any]] = []

    for check in sorted(quality_checks, key=lambda item: item.checked_at, reverse=True):
        if check.work_order_id not in work_order_ids or check.result != "rework":
            continue

        piece_numbers = sorted(
            {
                int(entry.get("piece_no"))
                for entry in (check.defect_details or [])
                if str(entry.get("piece_no", "")).isdigit()
            }
        )
        source_key = check.check_type
        rows.append(
            {
                "id": check.id,
                "sourceStepKey": source_key,
                "sourceStepLabel": STEP_LABELS.get(source_key, source_key),
                "pieceNumbers": piece_numbers,
                "pieceCount": check.defect_qty,
                "pieceSummary": format_piece_summary(piece_numbers),
                "note": check.remark or "",
                "actorName": "系统",
                "createdAt": check.checked_at,
                "isAcknowledged": not cutting_unread,
                "acknowledgedAt": None,
                "acknowledgedByName": "",
            }
        )

    return rows


async def serialize_order(
    session: AsyncSession,
    order: OrderModel,
    include_detail: bool = False,
    route_prefix: str = "/api",
    *,
    customer: CustomerModel | None = None,
    work_orders: list[WorkOrderModel] | None = None,
    quality_checks: list[QualityCheckModel] | None = None,
) -> dict[str, Any]:
    if customer is None:
        customer = await session.get(CustomerModel, order.customer_id)

    if work_orders is None:
        work_order_result = await session.execute(
            select(WorkOrderModel)
            .where(WorkOrderModel.order_id == order.id)
            .order_by(WorkOrderModel.created_at.asc())
        )
        work_orders = list(work_order_result.scalars().all())

    if quality_checks is None:
        quality_checks = []
        if work_orders:
            quality_result = await session.execute(
                select(QualityCheckModel)
                .where(QualityCheckModel.work_order_id.in_([row.id for row in work_orders]))
                .order_by(QualityCheckModel.checked_at.desc())
            )
            quality_checks = list(quality_result.scalars().all())

    first_item = order.items[0] if order.items else None
    current_step_key = "cutting"
    current_step_status = "pending"
    if work_orders:
        current_step_key = work_orders[0].process_step_key
        current_step_status = work_orders[0].status

    ui_status = to_ui_status(order.status)
    current_step_index = next(
        (index for index, step in enumerate(PRODUCTION_STEPS) if step["key"] == current_step_key),
        0,
    )

    step_rework_map: dict[str, list[int]] = {}
    for quality_check in quality_checks:
        if quality_check.result != "rework":
            continue
        bucket = step_rework_map.setdefault(quality_check.check_type, [])
        for detail in quality_check.defect_details or []:
            raw_piece_no = detail.get("piece_no")
            if str(raw_piece_no).isdigit():
                bucket.append(int(raw_piece_no))

    steps: list[dict[str, Any]] = []
    for index, step in enumerate(PRODUCTION_STEPS):
        step_key = step["key"]
        if ui_status in {"completed", "shipping", "delivered", "ready_for_pickup", "picked_up"}:
            step_status = "completed"
        elif index < current_step_index:
            step_status = "completed"
        elif index == current_step_index:
            step_status = current_step_status
        else:
            step_status = "pending"

        if ui_status == "cancelled" and step_status == "pending":
            step_status = "pending"

        rework_piece_numbers = sorted(
            {piece for piece in step_rework_map.get(step_key, []) if piece > 0}
        )
        rework_piece_summary = format_piece_summary(rework_piece_numbers)
        rework_unread = step_key == "cutting" and any(
            bool(row.rework_unread) for row in work_orders
        )

        steps.append(
            {
                "key": step_key,
                "label": step["label"],
                "status": step_status,
                "statusLabel": step_status_label(step_status),
                "startedAt": None,
                "completedAt": None,
                "updatedAt": order.updated_at,
                "reworkCount": len(rework_piece_numbers),
                "reworkNote": "",
                "reworkUnread": rework_unread,
                "isAvailable": index == 0
                or all(candidate["status"] == "completed" for candidate in steps[:index]),
                "isBlocked": index > 0
                and not all(candidate["status"] == "completed" for candidate in steps[:index]),
                "reworkPieceNumbers": rework_piece_numbers,
                "reworkPieceSummary": rework_piece_summary,
                "reworkRequestCount": len(rework_piece_numbers),
            }
        )

    for row in work_orders:
        for step in steps:
            if step["key"] != row.process_step_key:
                continue
            step["startedAt"] = row.started_at
            step["completedAt"] = row.completed_at
            step["updatedAt"] = row.updated_at
            if row.rework_unread and step["key"] == "cutting":
                step["reworkUnread"] = True
            break

    open_rework_piece_numbers = sorted(
        {piece for numbers in step_rework_map.values() for piece in numbers if piece > 0}
    )
    open_rework_piece_summary = format_piece_summary(open_rework_piece_numbers)

    stale_days = max(0, (datetime.now(timezone.utc) - order.updated_at).days)
    is_stale = ui_status not in {"delivered", "picked_up", "cancelled"} and stale_days >= 5
    pickup_waiting_days = 0
    if ui_status == "ready_for_pickup" and order.pickup_approved_at is not None:
        pickup_waiting_days = max(0, (datetime.now(timezone.utc) - order.pickup_approved_at).days)

    can_cancel = ui_status in {"received", "entered"} and not any(
        row.started_at is not None or row.completed_at is not None for row in work_orders
    )

    payload: dict[str, Any] = {
        "id": order.id,
        "orderNo": order.order_no,
        "status": ui_status,
        "statusLabel": status_label(ui_status),
        "priority": order.priority,
        "priorityLabel": priority_label(order.priority),
        "glassType": first_item.glass_type if first_item else "Clear",
        "thickness": first_item.specification if first_item else "6mm",
        "quantity": order.total_quantity,
        "estimatedCompletionDate": order.expected_delivery_date,
        "specialInstructions": order.remark,
        "drawingUrl": (
            build_order_asset_url(route_prefix, order.id, "drawing")
            if order.drawing_object_key
            else ""
        ),
        "drawingName": order.drawing_original_name,
        "createdAt": order.created_at,
        "updatedAt": order.updated_at,
        "enteredAt": order.confirmed_at,
        "completedAt": None,
        "cancelledAt": order.cancelled_at,
        "cancelledReason": order.cancelled_reason or "",
        "readyForPickupAt": order.pickup_approved_at,
        "pickedUpAt": order.picked_up_at,
        "pickupApprovedAt": order.pickup_approved_at,
        "pickupApprovedBy": order.pickup_approved_by,
        "pickupSignerName": order.pickup_signer_name,
        "pickupSignatureUrl": "",
        "version": order.version,
        "isModified": order.version > 1,
        "reworkOpen": bool(open_rework_piece_numbers)
        or any(bool(row.rework_unread) for row in work_orders),
        "staleDays": stale_days,
        "isStale": is_stale,
        "canCancel": can_cancel,
        "canCancelLabel": "撤回订单" if ui_status == "received" else "取消订单",
        "pickupWaitingDays": pickup_waiting_days,
        "customer": {
            "id": customer.id if customer else order.customer_id,
            "companyName": customer.company_name if customer else "未知客户",
            "contactName": customer.contact_name if customer else "",
            "phone": customer.phone if customer else "",
            "email": customer.email if customer else "",
            "notes": customer.address if customer else "",
        },
        "steps": steps,
        "reworkRequests": [],
        "openReworkCount": len(open_rework_piece_numbers),
        "openReworkPieceSummary": open_rework_piece_summary,
        "timeline": [],
        "versionHistory": [],
    }

    if include_detail:
        events_result = await session.execute(
            select(EventOutboxModel)
            .where(EventOutboxModel.event_key == order.id)
            .order_by(EventOutboxModel.created_at.desc())
            .limit(30)
        )
        events = list(events_result.scalars().all())
        payload["timeline"] = [
            {
                "id": event.id,
                "type": event.topic,
                "message": event.topic,
                "actorName": "系统",
                "createdAt": event.created_at,
                "metadata": event.payload or {},
            }
            for event in events
        ]
        payload["versionHistory"] = [
            {
                "id": f"v-{order.id}-{order.version}",
                "versionNumber": order.version,
                "summary": f"订单版本 {order.version}",
                "changedAt": order.updated_at,
                "actorName": "系统",
            }
        ]
        payload["reworkRequests"] = await serialize_rework_requests(work_orders, quality_checks)

    return payload
