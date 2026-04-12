from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domains.notifications.service import NotificationsService
from domains.orders.schema import CreateOrderItem, CreateOrderRequest
from domains.orders.service import OrdersService
from domains.workspace import ui_support as workspace_ui
from infra.core.errors import AppError
from infra.db.models.customers import CustomerModel
from infra.db.models.orders import OrderModel
from infra.db.models.settings import GlassTypeModel
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.identity import (
    can_create_orders,
    resolve_canonical_role,
    resolve_home_path,
    resolve_shell_name,
    resolve_user_scopes,
)
from infra.security.idempotency import enforce_idempotency_key
from infra.security.rbac import require_roles

router = APIRouter(prefix="/app", tags=["customer-app"])
customer_guard = require_roles(["customer", "customer_viewer"])
customer_writer_guard = require_roles(["customer"])
notifications_service = NotificationsService()
orders_service = OrdersService()


async def _load_customer_context(
    session: AsyncSession,
    auth_user: AuthUser,
) -> tuple[UserModel, CustomerModel]:
    user_model = await session.get(UserModel, auth_user.user_id)
    if user_model is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录。")
    if not user_model.customer_id:
        raise HTTPException(status_code=403, detail="当前账号未绑定客户身份。")

    customer = await session.get(CustomerModel, user_model.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户档案不存在。")

    return user_model, customer


def _serialize_profile(customer: CustomerModel) -> dict[str, Any]:
    return {
        "id": customer.id,
        "companyName": customer.company_name,
        "contactName": customer.contact_name,
        "phone": customer.phone,
        "email": customer.email,
        "address": customer.address,
        "priceLevel": customer.price_level,
    }


def _serialize_credit(customer: CustomerModel) -> dict[str, Any]:
    available_credit = customer.credit_limit - customer.credit_used
    return {
        "limit": customer.credit_limit,
        "used": customer.credit_used,
        "available": available_credit,
    }


async def _serialize_orders(session: AsyncSession, customer_id: str) -> list[dict[str, Any]]:
    orders_result = await session.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items))
        .where(OrderModel.customer_id == customer_id)
        .order_by(OrderModel.updated_at.desc())
        .limit(100)
    )
    orders = list(orders_result.scalars().all())
    return await workspace_ui.serialize_orders(
        session,
        orders,
        include_detail=False,
        route_prefix="/v1/app",
    )


async def _serialize_notifications(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    return await workspace_ui.serialize_notifications(session, user_id)


def _serialize_customer_user(user_model: UserModel, auth_user: AuthUser, customer_id: str) -> dict[str, Any]:
    canonical_role = resolve_canonical_role(user_model.role)
    resolved_scopes = resolve_user_scopes(
        user_model.role,
        scopes=auth_user.scopes or user_model.scopes or [],
        stage=user_model.stage,
    )
    return {
        "id": user_model.id,
        "name": user_model.display_name,
        "email": user_model.email,
        "role": canonical_role,
        "canonicalRole": canonical_role,
        "scopes": resolved_scopes,
        "customerId": customer_id,
        "homePath": resolve_home_path(user_model.role),
        "shell": resolve_shell_name(user_model.role),
        "canCreateOrders": can_create_orders(user_model.role),
    }


@router.get("/bootstrap")
async def customer_bootstrap(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user_model, customer = await _load_customer_context(session, auth_user)
    await workspace_ui.ensure_default_glass_types(session, user_model.id)

    glass_type_result = await session.execute(
        select(GlassTypeModel)
        .where(GlassTypeModel.is_active.is_(True))
        .order_by(GlassTypeModel.sort_order.asc(), GlassTypeModel.name.asc())
    )
    glass_type_names = [row.name for row in glass_type_result.scalars().all()]

    order_payloads = await _serialize_orders(session, customer.id)
    notifications = await _serialize_notifications(session, user_model.id)

    active_statuses = {"received", "entered", "in_production", "completed", "shipping", "ready_for_pickup"}
    credit_payload = _serialize_credit(customer)

    return {
        "user": _serialize_customer_user(user_model, auth_user, customer.id),
        "options": {
            "glassTypes": glass_type_names,
            "thicknessOptions": workspace_ui.DEFAULT_THICKNESS_OPTIONS,
            "priorities": workspace_ui.DEFAULT_PRIORITIES,
            "orderStatuses": workspace_ui.DEFAULT_ORDER_STATUSES,
        },
        "data": {
            "summary": {
                "totalOrders": len(order_payloads),
                "activeOrders": sum(1 for order in order_payloads if order["status"] in active_statuses),
                "readyForPickupOrders": sum(
                    1 for order in order_payloads if order["status"] == "ready_for_pickup"
                ),
                "completedOrders": sum(
                    1 for order in order_payloads if order["status"] in {"delivered", "picked_up"}
                ),
                "availableCredit": credit_payload["available"],
            },
            "profile": _serialize_profile(customer),
            "credit": credit_payload,
            "orders": order_payloads,
            "notifications": notifications,
        },
    }


@router.get("/orders")
async def customer_list_orders(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _, customer = await _load_customer_context(session, auth_user)
    return {"orders": await _serialize_orders(session, customer.id)}


@router.get("/profile")
async def customer_profile(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _, customer = await _load_customer_context(session, auth_user)
    return {"profile": _serialize_profile(customer)}


@router.get("/credit")
async def customer_credit(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _, customer = await _load_customer_context(session, auth_user)
    return {"credit": _serialize_credit(customer)}


@router.get("/orders/{order_id}")
async def customer_order_detail(
    order_id: str,
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _, customer = await _load_customer_context(session, auth_user)
    result = await session.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items))
        .where(OrderModel.id == order_id, OrderModel.customer_id == customer.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await workspace_ui.serialize_order(session, order, include_detail=True, route_prefix="/v1/app")}


@router.get("/notifications")
async def customer_notifications(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    user_model, _ = await _load_customer_context(session, auth_user)
    return {"notifications": await _serialize_notifications(session, user_model.id)}


@router.post("/orders")
async def customer_create_order(
    glassType: str = Form(...),
    thickness: str = Form(...),
    quantity: int = Form(...),
    priority: str = Form("normal"),
    estimatedCompletionDate: str | None = Form(None),
    specialInstructions: str = Form(""),
    drawing: UploadFile | None = File(default=None),
    auth_user: AuthUser = Depends(customer_writer_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    user_model, customer = await _load_customer_context(session, auth_user)
    effective_idempotency_key = await enforce_idempotency_key("app:orders:create", idempotency_key)

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="数量必须大于 0。")

    product = await workspace_ui.ensure_product_inventory(session, glassType, thickness, quantity)
    request_payload = CreateOrderRequest(
        customer_id=customer.id,
        delivery_address=customer.address or "factory-pickup",
        expected_delivery_date=workspace_ui.parse_date_input(estimatedCompletionDate),
        priority=priority,
        remark=specialInstructions,
        idempotency_key=effective_idempotency_key,
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

    result = await session.execute(
        select(OrderModel).options(selectinload(OrderModel.items)).where(OrderModel.id == order_view.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在。")

    return {"order": await workspace_ui.serialize_order(session, order, include_detail=True, route_prefix="/v1/app")}


@router.post("/notifications/read")
async def customer_mark_notifications_read(
    auth_user: AuthUser = Depends(customer_guard),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    await enforce_idempotency_key("app:notifications:mark-read", idempotency_key)
    await notifications_service.mark_notifications_read(session, auth_user.user_id)
    return {"notifications": await _serialize_notifications(session, auth_user.user_id)}