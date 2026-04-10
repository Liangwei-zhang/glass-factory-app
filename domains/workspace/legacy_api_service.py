from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domains.auth.schema import LoginRequest
from domains.auth.service import AuthService
from domains.orders.schema import (
    CreateOrderItem,
    CreateOrderRequest,
    PickupSignatureRequest,
    UpdateOrderItemRequest,
    UpdateOrderRequest,
)
from domains.orders.service import OrdersService
from infra.cache.redis_client import get_redis
from infra.core.errors import AppError
from infra.db.models.customers import CustomerModel
from infra.db.models.events import EventOutboxModel
from infra.db.models.inventory import InventoryModel, ProductModel
from infra.db.models.notifications import NotificationModel
from infra.db.models.orders import OrderModel, OrderItemModel
from infra.db.models.production import QualityCheckModel, WorkOrderModel
from infra.db.models.settings import EmailLogModel, GlassTypeModel, NotificationTemplateModel
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, create_access_token, get_current_user
from infra.storage.object_storage import ObjectStorage

router = APIRouter(prefix="/api", tags=["legacy-api"])
auth_service = AuthService()
orders_service = OrdersService()
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

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
STAGE_LABELS = {
    "cutting": "切玻璃工人",
    "edging": "开切口工人",
    "tempering": "钢化工人",
    "finishing": "完成钢化处工人",
}
PICKUP_TEMPLATE_KEY = "ready_for_pickup"
DEFAULT_TEMPLATE = {
    "name": "Ready for Pickup 邮件",
    "subject_template": "订单 {{orderNo}} 已可取货",
    "body_template": "您好 {{customerName}}，\n\n订单 {{orderNo}} 已可取货。\n玻璃类型：{{glassType}}\n规格：{{specification}}\n数量：{{quantity}}\n\n请安排到厂取货。\n",
}


def _refresh_session_id(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _refresh_session_key(refresh_token: str) -> str:
    return f"session:{_refresh_session_id(refresh_token)}"


def _to_ui_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized in {"admin", "manager", "supervisor"}:
        return "supervisor"
    if normalized in {"worker"}:
        return "worker"
    return "office"


def _to_ui_status(status: str) -> str:
    if status in {"pending", "confirmed"}:
        return "received"
    if status in {
        "entered",
        "in_production",
        "completed",
        "ready_for_pickup",
        "picked_up",
        "cancelled",
    }:
        return status
    return "received"


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _priority_label(priority: str) -> str:
    return PRIORITY_LABELS.get(priority, priority)


def _step_status_label(status: str) -> str:
    return STEP_STATUS_LABELS.get(status, status)


def _parse_date_input(value: str | None) -> datetime:
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


def _format_piece_summary(piece_numbers: list[int]) -> str:
    normalized = sorted({piece for piece in piece_numbers if piece > 0})
    if not normalized:
        return ""
    return "、".join(f"第 {piece} 片" for piece in normalized)


def _render_template(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _assert_roles(user: AuthUser, allowed_roles: set[str]) -> None:
    role = _to_ui_role(user.role)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="当前角色无权执行此操作。")


async def _get_user_model(session: AsyncSession, auth_user: AuthUser) -> UserModel:
    row = await session.get(UserModel, auth_user.user_id)
    if row is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。")
    return row


async def _ensure_default_glass_types(session: AsyncSession, actor_user_id: str | None = None) -> None:
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


async def _ensure_pickup_template(
    session: AsyncSession,
    actor_user_id: str | None,
) -> NotificationTemplateModel:
    result = await session.execute(
        select(NotificationTemplateModel).where(
            NotificationTemplateModel.template_key == PICKUP_TEMPLATE_KEY
        )
    )
    template = result.scalar_one_or_none()
    if template is not None:
        return template

    template = NotificationTemplateModel(
        template_key=PICKUP_TEMPLATE_KEY,
        name=DEFAULT_TEMPLATE["name"],
        subject_template=DEFAULT_TEMPLATE["subject_template"],
        body_template=DEFAULT_TEMPLATE["body_template"],
        updated_at=datetime.now(timezone.utc),
        updated_by=actor_user_id,
    )
    session.add(template)
    await session.flush()
    return template


async def _ensure_product_inventory(
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
    target_available = max(required_quantity * 2, 100)
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
    elif inventory.available_qty < required_quantity:
        inventory.available_qty = target_available
        inventory.total_qty = inventory.available_qty + inventory.reserved_qty
        inventory.version += 1

    await session.flush()
    return product


async def _serialize_customers(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        select(CustomerModel).order_by(CustomerModel.updated_at.desc())
    )
    customers = list(result.scalars().all())

    rows: list[dict[str, Any]] = []
    active_statuses = {
        "pending",
        "confirmed",
        "entered",
        "in_production",
        "completed",
        "ready_for_pickup",
    }

    for customer in customers:
        order_stats_result = await session.execute(
            select(OrderModel.status, OrderModel.created_at).where(
                OrderModel.customer_id == customer.id
            )
        )
        order_stats = list(order_stats_result.all())
        total_orders = len(order_stats)
        active_orders = sum(1 for status, _ in order_stats if status in active_statuses)
        last_order_at = max((created_at for _, created_at in order_stats), default=None)

        rows.append(
            {
                "id": customer.id,
                "companyName": customer.company_name,
                "contactName": customer.contact_name,
                "phone": customer.phone,
                "email": customer.email,
                "notes": customer.address or "",
                "totalOrders": total_orders,
                "activeOrders": active_orders,
                "hasActiveOrders": active_orders > 0,
                "lastOrderAt": last_order_at,
                "createdAt": customer.created_at,
                "updatedAt": customer.updated_at,
            }
        )

    return rows


async def _serialize_notifications(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
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


async def _serialize_rework_requests(
    session: AsyncSession,
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
                "pieceSummary": _format_piece_summary(piece_numbers),
                "note": check.remark or "",
                "actorName": "系统",
                "createdAt": check.checked_at,
                "isAcknowledged": not cutting_unread,
                "acknowledgedAt": None,
                "acknowledgedByName": "",
            }
        )

    return rows


async def _serialize_order(
    session: AsyncSession,
    order: OrderModel,
    include_detail: bool = False,
) -> dict[str, Any]:
    customer = await session.get(CustomerModel, order.customer_id)

    work_order_result = await session.execute(
        select(WorkOrderModel)
        .where(WorkOrderModel.order_id == order.id)
        .order_by(WorkOrderModel.created_at.asc())
    )
    work_orders = list(work_order_result.scalars().all())

    quality_checks: list[QualityCheckModel] = []
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

    ui_status = _to_ui_status(order.status)
    current_step_index = next(
        (
            index
            for index, step in enumerate(PRODUCTION_STEPS)
            if step["key"] == current_step_key
        ),
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
        if ui_status in {"completed", "ready_for_pickup", "picked_up"}:
            step_status = "completed"
        elif index < current_step_index:
            step_status = "completed"
        elif index == current_step_index:
            step_status = current_step_status
        else:
            step_status = "pending"

        if ui_status == "cancelled" and step_status == "pending":
            step_status = "pending"

        rework_piece_numbers = sorted({piece for piece in step_rework_map.get(step_key, []) if piece > 0})
        rework_piece_summary = _format_piece_summary(rework_piece_numbers)
        rework_unread = (
            step_key == "cutting" and any(bool(row.rework_unread) for row in work_orders)
        )

        steps.append(
            {
                "key": step_key,
                "label": step["label"],
                "status": step_status,
                "statusLabel": _step_status_label(step_status),
                "startedAt": None,
                "completedAt": None,
                "updatedAt": order.updated_at,
                "reworkCount": len(rework_piece_numbers),
                "reworkNote": "",
                "reworkUnread": rework_unread,
                "isAvailable": index == 0 or all(
                    candidate["status"] == "completed" for candidate in steps[:index]
                ),
                "isBlocked": index > 0 and not all(
                    candidate["status"] == "completed" for candidate in steps[:index]
                ),
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
        {
            piece
            for numbers in step_rework_map.values()
            for piece in numbers
            if piece > 0
        }
    )
    open_rework_piece_summary = _format_piece_summary(open_rework_piece_numbers)

    stale_days = max(0, (datetime.now(timezone.utc) - order.updated_at).days)
    is_stale = ui_status not in {"picked_up", "cancelled"} and stale_days >= 5
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
        "statusLabel": _status_label(ui_status),
        "priority": order.priority,
        "priorityLabel": _priority_label(order.priority),
        "glassType": first_item.glass_type if first_item else "Clear",
        "thickness": first_item.specification if first_item else "6mm",
        "quantity": order.total_quantity,
        "estimatedCompletionDate": order.expected_delivery_date,
        "specialInstructions": order.remark,
        "drawingUrl": f"/api/orders/{order.id}/drawing" if order.drawing_object_key else "",
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
        "reworkOpen": bool(open_rework_piece_numbers) or any(
            bool(row.rework_unread) for row in work_orders
        ),
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
                "eventType": "updated" if order.version > 1 else "created",
                "eventLabel": "订单修改" if order.version > 1 else "初始版本",
                "reason": "",
                "actorName": "系统",
                "createdAt": order.updated_at,
                "snapshot": {},
                "changes": [],
            }
        ]
        payload["reworkRequests"] = await _serialize_rework_requests(
            session,
            work_orders,
            quality_checks,
        )

    return payload


def _serialize_template(template: NotificationTemplateModel, updated_by_name: str | None) -> dict[str, Any]:
    return {
        "templateKey": template.template_key,
        "name": template.name,
        "subjectTemplate": template.subject_template,
        "bodyTemplate": template.body_template,
        "availableVariables": [
            "customerName",
            "orderNo",
            "glassType",
            "specification",
            "quantity",
        ],
        "updatedAt": template.updated_at,
        "updatedByName": updated_by_name or "",
    }


def _serialize_email_log(log: EmailLogModel, order_no: str | None) -> dict[str, Any]:
    return {
        "id": log.id,
        "templateKey": log.template_key,
        "orderId": log.order_id,
        "orderNo": order_no,
        "customerEmail": log.customer_email,
        "subject": log.subject,
        "body": log.body,
        "status": log.status,
        "transport": log.transport,
        "errorMessage": log.error_message,
        "providerMessageId": log.provider_message_id,
        "createdAt": log.created_at,
        "sentAt": log.sent_at,
    }


@router.post("/auth/login")
async def api_login(
    payload: dict[str, Any] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    principal = str(payload.get("email") or payload.get("username") or "").strip()
    password = str(payload.get("password") or "")

    if not principal or not password:
        raise HTTPException(status_code=400, detail="请输入邮箱和密码。")

    try:
        login_result = await auth_service.login(
            session,
            LoginRequest(email=principal, password=password),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    user_model = await session.get(UserModel, login_result.user.id)
    if user_model is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。")

    refresh_token = secrets.token_urlsafe(48)
    session_id = _refresh_session_id(refresh_token)
    redis = await get_redis()
    await redis.set(
        _refresh_session_key(refresh_token),
        json.dumps(
            {
                "user_id": user_model.id,
                "role": user_model.role,
                "scopes": login_result.user.scopes,
                "stage": user_model.stage,
            }
        ),
        ex=REFRESH_TOKEN_TTL_SECONDS,
    )

    access_token = create_access_token(
        subject=user_model.id,
        role=user_model.role,
        scopes=login_result.user.scopes,
        stage=user_model.stage,
        session_id=session_id,
    )

    ui_role = _to_ui_role(user_model.role)
    stage = user_model.stage
    return {
        "token": access_token,
        "refreshToken": refresh_token,
        "user": {
            "id": user_model.id,
            "name": user_model.display_name,
            "email": user_model.email,
            "role": ui_role,
            "stage": stage,
            "stageLabel": STAGE_LABELS.get(stage or ""),
        },
    }


@router.get("/me")
async def api_me(
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user_model = await _get_user_model(session, auth_user)
    return {
        "user": {
            "id": user_model.id,
            "name": user_model.display_name,
            "email": user_model.email,
            "role": _to_ui_role(user_model.role),
            "stage": user_model.stage,
            "stageLabel": STAGE_LABELS.get(user_model.stage or ""),
        }
    }


@router.get("/bootstrap")
async def api_bootstrap(
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user_model = await _get_user_model(session, auth_user)
    await _ensure_default_glass_types(session, user_model.id)
    await _ensure_pickup_template(session, user_model.id)

    glass_type_result = await session.execute(
        select(GlassTypeModel)
        .where(GlassTypeModel.is_active.is_(True))
        .order_by(GlassTypeModel.sort_order.asc(), GlassTypeModel.name.asc())
    )
    glass_type_names = [row.name for row in glass_type_result.scalars().all()]

    order_result = await session.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items))
        .order_by(OrderModel.updated_at.desc())
        .limit(300)
    )
    orders = list(order_result.scalars().all())
    order_payloads = [await _serialize_order(session, order) for order in orders]

    customers = await _serialize_customers(session)
    notifications = await _serialize_notifications(session, user_model.id)

    active_statuses = {"received", "entered", "in_production", "completed", "ready_for_pickup"}
    summary = {
        "totalOrders": len(order_payloads),
        "activeOrders": sum(1 for order in order_payloads if order["status"] in active_statuses),
        "inProductionOrders": sum(1 for order in order_payloads if order["status"] == "in_production"),
        "readyForPickupOrders": sum(
            1 for order in order_payloads if order["status"] == "ready_for_pickup"
        ),
        "staleOrders": sum(1 for order in order_payloads if order["isStale"]),
        "rushOrders": sum(1 for order in order_payloads if order["priority"] == "rush"),
        "reworkOrders": sum(1 for order in order_payloads if order["reworkOpen"]),
        "modifiedOrders": sum(1 for order in order_payloads if order["isModified"]),
        "activeCustomers": sum(1 for customer in customers if customer["hasActiveOrders"]),
    }

    if _to_ui_role(user_model.role) == "worker" and user_model.stage:
        worker_orders = []
        for order in order_payloads:
            step = next(
                (candidate for candidate in order["steps"] if candidate["key"] == user_model.stage),
                None,
            )
            if step and step["status"] != "completed":
                worker_orders.append(order)
        summary["workerQueue"] = len(worker_orders)
        summary["workerReady"] = sum(
            1
            for order in worker_orders
            for step in order["steps"]
            if step["key"] == user_model.stage and (step["isAvailable"] or step["status"] == "in_progress")
        )

    return {
        "user": {
            "id": user_model.id,
            "name": user_model.display_name,
            "email": user_model.email,
            "role": _to_ui_role(user_model.role),
            "stage": user_model.stage,
            "stageLabel": STAGE_LABELS.get(user_model.stage or ""),
        },
        "options": {
            "glassTypes": glass_type_names,
            "thicknessOptions": DEFAULT_THICKNESS_OPTIONS,
            "priorities": DEFAULT_PRIORITIES,
            "orderStatuses": DEFAULT_ORDER_STATUSES,
            "productionSteps": PRODUCTION_STEPS,
        },
        "data": {
            "summary": summary,
            "customers": customers,
            "orders": order_payloads,
            "notifications": notifications,
        },
    }


@router.get("/customers")
async def api_list_customers(
    _auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return {"customers": await _serialize_customers(session)}


@router.post("/customers")
async def api_create_customer(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    company_name = str(payload.get("companyName") or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="公司名称不能为空。")

    now = datetime.now(timezone.utc)
    customer = CustomerModel(
        customer_code=f"CUST-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        company_name=company_name,
        contact_name=str(payload.get("contactName") or "").strip() or None,
        phone=str(payload.get("phone") or "").strip() or None,
        email=str(payload.get("email") or "").strip() or None,
        address=str(payload.get("notes") or "").strip() or None,
        credit_limit=Decimal("0"),
        credit_used=Decimal("0"),
        is_active=True,
    )
    session.add(customer)
    await session.flush()

    return {
        "customer": {
            "id": customer.id,
            "companyName": customer.company_name,
            "contactName": customer.contact_name,
            "phone": customer.phone,
            "email": customer.email,
            "notes": customer.address or "",
        },
        "customers": await _serialize_customers(session),
    }


@router.patch("/customers/{customer_id}")
async def api_update_customer(
    customer_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    customer = await session.get(CustomerModel, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在。")

    if "companyName" in payload:
        company_name = str(payload.get("companyName") or "").strip()
        if not company_name:
            raise HTTPException(status_code=400, detail="公司名称不能为空。")
        customer.company_name = company_name

    if "contactName" in payload:
        customer.contact_name = str(payload.get("contactName") or "").strip() or None
    if "phone" in payload:
        customer.phone = str(payload.get("phone") or "").strip() or None
    if "email" in payload:
        customer.email = str(payload.get("email") or "").strip() or None
    if "notes" in payload:
        customer.address = str(payload.get("notes") or "").strip() or None

    await session.flush()

    return {
        "customer": {
            "id": customer.id,
            "companyName": customer.company_name,
            "contactName": customer.contact_name,
            "phone": customer.phone,
            "email": customer.email,
            "notes": customer.address or "",
        },
        "customers": await _serialize_customers(session),
    }


@router.get("/orders")
async def api_list_orders(
    query: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    _auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await session.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items))
        .order_by(OrderModel.updated_at.desc())
        .limit(500)
    )
    rows = list(result.scalars().all())

    payloads = []
    normalized_query = (query or "").strip().lower()
    for row in rows:
        serialized = await _serialize_order(session, row)

        if normalized_query:
            keyword = " ".join(
                [
                    serialized["orderNo"],
                    serialized["customer"].get("companyName") or "",
                    serialized["customer"].get("phone") or "",
                    serialized["customer"].get("email") or "",
                ]
            ).lower()
            if normalized_query not in keyword:
                continue

        if status and status != "all" and serialized["status"] != status:
            continue
        if priority and priority != "all" and serialized["priority"] != priority:
            continue

        payloads.append(serialized)

    return {"orders": payloads}


@router.get("/orders/{order_id}")
async def api_get_order(
    order_id: str,
    _auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.get("/orders/{order_id}/drawing")
async def api_download_drawing(
    order_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    result = await session.execute(
        select(OrderModel).where(OrderModel.id == order_id)
    )
    row = result.scalar_one_or_none()
    if row is None or not row.drawing_object_key:
        raise HTTPException(status_code=404, detail="图纸不存在。")

    storage = ObjectStorage()
    local_path = storage.resolve_local_path("drawings", row.drawing_object_key)
    if not local_path.exists():
        raise HTTPException(status_code=404, detail="图纸不存在。")

    return FileResponse(path=local_path, filename=row.drawing_original_name or "drawing.pdf")


@router.get("/orders/{order_id}/export")
async def api_export_order(
    order_id: str,
    document: str = Query(default="order"),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    _ = auth_user
    try:
        payload = await orders_service.export_document_pdf(
            session,
            order_id=order_id,
            document=document,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    filename = f"{order_id}-{document}.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/orders")
async def api_create_order(
    customerId: str = Form(...),
    glassType: str = Form(...),
    thickness: str = Form(...),
    quantity: int = Form(...),
    priority: str = Form("normal"),
    estimatedCompletionDate: str | None = Form(None),
    specialInstructions: str = Form(""),
    drawing: UploadFile | None = File(default=None),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    customer = await session.get(CustomerModel, customerId)
    if customer is None:
        raise HTTPException(status_code=404, detail="请选择有效客户。")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于 0。")

    product = await _ensure_product_inventory(session, glassType, thickness, quantity)
    request_payload = CreateOrderRequest(
        customer_id=customer.id,
        delivery_address=customer.address or "factory-pickup",
        expected_delivery_date=_parse_date_input(estimatedCompletionDate),
        priority=priority,
        remark=specialInstructions,
        items=[
            CreateOrderItem(
                product_id=product.id,
                product_name=product.product_name,
                glass_type=glassType.strip() or "Clear",
                specification=thickness.strip() or "6mm",
                width_mm=1000,
                height_mm=1000,
                quantity=quantity,
                unit_price=Decimal("1.00"),
                process_requirements=specialInstructions,
            )
        ],
    )

    try:
        order_view = await orders_service.create_order(session, request_payload)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if drawing is not None:
        payload_bytes = await drawing.read()
        if payload_bytes:
            await orders_service.upload_drawing(
                session,
                order_id=order_view.id,
                filename=drawing.filename or "drawing.pdf",
                payload_bytes=payload_bytes,
            )

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_view.id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.put("/orders/{order_id}")
async def api_update_order(
    order_id: str,
    glassType: str | None = Form(default=None),
    thickness: str | None = Form(default=None),
    quantity: int | None = Form(default=None),
    priority: str | None = Form(default=None),
    estimatedCompletionDate: str | None = Form(default=None),
    specialInstructions: str | None = Form(default=None),
    drawing: UploadFile | None = File(default=None),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")
    if not order.items:
        raise HTTPException(status_code=409, detail="订单缺少明细，无法更新。")

    first_item = order.items[0]
    item_update = UpdateOrderItemRequest(id=first_item.id)

    if glassType is not None:
        item_update.glass_type = glassType.strip() or first_item.glass_type
    if thickness is not None:
        item_update.specification = thickness.strip() or first_item.specification
    if quantity is not None:
        if quantity <= 0:
            raise HTTPException(status_code=400, detail="数量必须大于 0。")
        item_update.quantity = quantity

    update_payload = UpdateOrderRequest(
        expected_delivery_date=_parse_date_input(estimatedCompletionDate)
        if estimatedCompletionDate is not None
        else None,
        priority=priority,
        remark=specialInstructions,
        items=[item_update],
    )

    try:
        await orders_service.update_order(
            session,
            order_id=order_id,
            payload=update_payload,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if drawing is not None:
        payload_bytes = await drawing.read()
        if payload_bytes:
            await orders_service.upload_drawing(
                session,
                order_id=order_id,
                filename=drawing.filename or "drawing.pdf",
                payload_bytes=payload_bytes,
            )

    updated_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    updated = updated_result.scalar_one_or_none()
    if updated is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, updated, include_detail=True)}


@router.post("/orders/{order_id}/cancel")
async def api_cancel_order(
    order_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    try:
        await orders_service.cancel_order(
            session,
            order_id=order_id,
            reason=str(payload.get("reason") or ""),
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")
    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.post("/orders/{order_id}/entered")
async def api_mark_entered(
    order_id: str,
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    try:
        await orders_service.mark_entered(session, order_id=order_id, actor_user_id=auth_user.user_id)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.post("/orders/{order_id}/steps/{step_key}")
async def api_step_action(
    order_id: str,
    step_key: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"worker", "supervisor"})

    action = str(payload.get("action") or "start")
    raw_pieces = payload.get("pieceNumbers") or payload.get("piece_numbers") or []
    piece_numbers = [int(item) for item in raw_pieces if str(item).isdigit()]
    note = str(payload.get("note") or "")

    try:
        await orders_service.apply_step_action(
            session,
            order_id=order_id,
            step_key=step_key,
            action=action,
            actor_user_id=auth_user.user_id,
            actor_role=_to_ui_role(auth_user.role),
            actor_stage=auth_user.stage,
            piece_numbers=piece_numbers,
            note=note,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.post("/orders/{order_id}/pickup/approve")
async def api_pickup_approve(
    order_id: str,
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"supervisor"})

    try:
        await orders_service.approve_pickup(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
        email_payload = await orders_service.send_pickup_email(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    response = {"order": await _serialize_order(session, order, include_detail=True)}
    response.update(email_payload)
    return response


@router.post("/orders/{order_id}/pickup/send-email")
async def api_pickup_send_email(
    order_id: str,
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    try:
        return await orders_service.send_pickup_email(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/orders/{order_id}/pickup/signature")
async def api_pickup_signature(
    order_id: str,
    payload: PickupSignatureRequest,
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    try:
        await orders_service.save_pickup_signature(
            session,
            order_id=order_id,
            actor_user_id=auth_user.user_id,
            signer_name=payload.signer_name,
            signature_data_url=payload.signature_data_url,
        )
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_id)
    )
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await _serialize_order(session, order, include_detail=True)}


@router.get("/notifications")
async def api_notifications(
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return {"notifications": await _serialize_notifications(session, auth_user.user_id)}


@router.post("/notifications/read")
async def api_mark_notifications_read(
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    await session.execute(
        update(NotificationModel)
        .where(NotificationModel.user_id == auth_user.user_id)
        .values(is_read=True)
    )
    return {"notifications": await _serialize_notifications(session, auth_user.user_id)}


@router.get("/settings/glass-types")
async def api_list_glass_types(
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})
    await _ensure_default_glass_types(session, auth_user.user_id)

    result = await session.execute(
        select(GlassTypeModel).order_by(GlassTypeModel.sort_order.asc(), GlassTypeModel.name.asc())
    )
    rows = list(result.scalars().all())
    return {
        "glassTypes": [
            {
                "id": row.id,
                "name": row.name,
                "isActive": bool(row.is_active),
                "sortOrder": row.sort_order,
                "totalOrderCount": 0,
                "activeOrderCount": 0,
                "updatedAt": row.updated_at,
                "updatedByName": "",
            }
            for row in rows
        ]
    }


@router.post("/settings/glass-types")
async def api_create_glass_type(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="玻璃类型名称不能为空。")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="玻璃类型名称不能超过 64 个字符。")

    duplicate = await session.execute(
        select(GlassTypeModel).where(func.lower(GlassTypeModel.name) == name.lower())
    )
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="玻璃类型已存在。")

    max_sort_order = await session.scalar(select(func.coalesce(func.max(GlassTypeModel.sort_order), -1)))
    glass_type = GlassTypeModel(
        name=name,
        is_active=True,
        sort_order=int(max_sort_order or -1) + 1,
        updated_at=datetime.now(timezone.utc),
        updated_by=auth_user.user_id,
    )
    session.add(glass_type)
    await session.flush()

    listing = await api_list_glass_types(auth_user, session)
    return {
        "glassType": {
            "id": glass_type.id,
            "name": glass_type.name,
            "isActive": glass_type.is_active,
            "sortOrder": glass_type.sort_order,
            "totalOrderCount": 0,
            "activeOrderCount": 0,
            "updatedAt": glass_type.updated_at,
            "updatedByName": "",
        },
        "glassTypes": listing["glassTypes"],
    }


@router.patch("/settings/glass-types/{glass_type_id}")
async def api_update_glass_type(
    glass_type_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    row = await session.get(GlassTypeModel, glass_type_id)
    if row is None:
        raise HTTPException(status_code=404, detail="玻璃类型不存在。")

    original_name = row.name
    if "name" in payload:
        next_name = str(payload.get("name") or "").strip()
        if not next_name:
            raise HTTPException(status_code=400, detail="玻璃类型名称不能为空。")
        if len(next_name) > 64:
            raise HTTPException(status_code=400, detail="玻璃类型名称不能超过 64 个字符。")
        duplicate = await session.execute(
            select(GlassTypeModel)
            .where(func.lower(GlassTypeModel.name) == next_name.lower())
            .where(GlassTypeModel.id != row.id)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="玻璃类型已存在。")

        row.name = next_name
        await session.execute(
            update(OrderItemModel)
            .where(func.lower(OrderItemModel.glass_type) == original_name.lower())
            .values(glass_type=next_name)
        )

    if "isActive" in payload:
        row.is_active = bool(payload.get("isActive"))

    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = auth_user.user_id
    await session.flush()

    listing = await api_list_glass_types(auth_user, session)
    return {
        "glassType": {
            "id": row.id,
            "name": row.name,
            "isActive": bool(row.is_active),
            "sortOrder": row.sort_order,
            "totalOrderCount": 0,
            "activeOrderCount": 0,
            "updatedAt": row.updated_at,
            "updatedByName": "",
        },
        "glassTypes": listing["glassTypes"],
    }


@router.get("/settings/notification-templates/{template_key}")
async def api_get_notification_template(
    template_key: str,
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})
    if template_key != PICKUP_TEMPLATE_KEY:
        raise HTTPException(status_code=404, detail="模板不存在。")

    template = await _ensure_pickup_template(session, auth_user.user_id)
    updated_by_name = ""
    if template.updated_by:
        updated_user = await session.get(UserModel, template.updated_by)
        updated_by_name = updated_user.display_name if updated_user else ""

    return {"template": _serialize_template(template, updated_by_name)}


@router.put("/settings/notification-templates/{template_key}")
async def api_update_notification_template(
    template_key: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})
    if template_key != PICKUP_TEMPLATE_KEY:
        raise HTTPException(status_code=404, detail="模板不存在。")

    subject_template = str(payload.get("subjectTemplate") or "").strip()
    body_template = str(payload.get("bodyTemplate") or "").strip()
    if not subject_template:
        raise HTTPException(status_code=400, detail="标题模板不能为空。")
    if not body_template:
        raise HTTPException(status_code=400, detail="正文模板不能为空。")

    template = await _ensure_pickup_template(session, auth_user.user_id)
    template.subject_template = subject_template
    template.body_template = body_template
    template.updated_at = datetime.now(timezone.utc)
    template.updated_by = auth_user.user_id
    await session.flush()

    updated_user = await session.get(UserModel, auth_user.user_id)
    return {
        "template": _serialize_template(
            template,
            updated_user.display_name if updated_user else "",
        )
    }


@router.get("/email-logs")
async def api_list_email_logs(
    limit: int = Query(default=20, ge=1, le=100),
    auth_user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _assert_roles(auth_user, {"office", "supervisor"})

    result = await session.execute(
        select(EmailLogModel)
        .order_by(EmailLogModel.created_at.desc())
        .limit(limit)
    )
    logs = list(result.scalars().all())

    order_map: dict[str, str] = {}
    order_ids = [entry.order_id for entry in logs if entry.order_id]
    if order_ids:
        order_result = await session.execute(
            select(OrderModel.id, OrderModel.order_no).where(OrderModel.id.in_(order_ids))
        )
        order_map = {row_id: order_no for row_id, order_no in order_result.all()}

    return {
        "logs": [
            _serialize_email_log(log, order_map.get(log.order_id or "")) for log in logs
        ]
    }