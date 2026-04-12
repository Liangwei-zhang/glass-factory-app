from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domains.customers.schema import DEFAULT_CUSTOMER_CREDIT_LIMIT
from domains.orders.schema import (
    CreateOrderItem,
    CreateOrderRequest,
    UpdateOrderItemRequest,
    UpdateOrderRequest,
)
from domains.orders.service import OrdersService
from domains.workspace import ui_support
from infra.core.errors import AppError, ErrorCode
from infra.db.models.customers import CustomerModel
from infra.db.models.orders import OrderModel
from infra.storage.object_storage import ObjectStorage

orders_service = OrdersService()
WORKSPACE_DEFAULT_CREDIT_LIMIT = DEFAULT_CUSTOMER_CREDIT_LIMIT


def normalize_piece_numbers(raw_pieces: Any) -> list[int]:
    return [int(item) for item in (raw_pieces or []) if str(item).isdigit()]


def order_matches_filters(
    order: dict[str, Any],
    *,
    query: str | None = None,
    status: str | None = None,
    priority: str | None = None,
) -> bool:
    normalized_query = (query or "").strip().lower()
    if normalized_query:
        customer = order.get("customer") or {}
        keyword = " ".join(
            [
                str(order.get("orderNo") or ""),
                str(customer.get("companyName") or ""),
                str(customer.get("phone") or ""),
                str(customer.get("email") or ""),
            ]
        ).lower()
        if normalized_query not in keyword:
            return False

    if status and status != "all" and order.get("status") != status:
        return False
    if priority and priority != "all" and order.get("priority") != priority:
        return False
    return True


def ensure_workspace_customer_credit_limit(customer: CustomerModel) -> bool:
    if customer.credit_limit > Decimal("0"):
        return False
    customer.credit_limit = WORKSPACE_DEFAULT_CREDIT_LIMIT
    return True


async def get_order_model(
    session: AsyncSession,
    order_id: str,
    *,
    include_items: bool = True,
) -> OrderModel:
    stmt = select(OrderModel).where(OrderModel.id == order_id)
    if include_items:
        stmt = stmt.options(selectinload(OrderModel.items))
    result = await session.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="订单不存在。",
            status_code=404,
            details={"order_id": order_id},
        )
    return order


async def serialize_workspace_order(
    session: AsyncSession,
    order_id: str,
    *,
    include_detail: bool = True,
) -> dict[str, Any]:
    order = await get_order_model(session, order_id, include_items=True)
    return await ui_support.serialize_order(
        session,
        order,
        include_detail=include_detail,
        route_prefix="/v1/workspace",
    )


async def list_workspace_orders(
    session: AsyncSession,
    *,
    query: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(OrderModel)
        .options(selectinload(OrderModel.items))
        .order_by(OrderModel.updated_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    serialized_orders = await ui_support.serialize_orders(
        session,
        rows,
        route_prefix="/v1/workspace",
    )

    payloads: list[dict[str, Any]] = []
    for serialized in serialized_orders:
        if order_matches_filters(serialized, query=query, status=status, priority=priority):
            payloads.append(serialized)
    return payloads


async def get_workspace_order(
    session: AsyncSession,
    order_id: str,
) -> dict[str, Any]:
    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}


async def get_order_drawing_file(
    session: AsyncSession,
    order_id: str,
) -> tuple[Path, str]:
    order = await get_order_model(session, order_id, include_items=False)
    if not order.drawing_object_key:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="图纸不存在。",
            status_code=404,
            details={"order_id": order_id},
        )

    storage = ObjectStorage()
    local_path = storage.resolve_local_path("drawings", order.drawing_object_key)
    if not local_path.exists():
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="图纸不存在。",
            status_code=404,
            details={"order_id": order_id},
        )
    return local_path, order.drawing_original_name or "drawing.pdf"


async def export_workspace_order_document(
    session: AsyncSession,
    order_id: str,
    *,
    document: str = "order",
) -> bytes:
    return await orders_service.export_document_pdf(session, order_id=order_id, document=document)


async def create_workspace_order(
    session: AsyncSession,
    *,
    customer_id: str,
    glass_type: str,
    thickness: str,
    quantity: int,
    priority: str,
    estimated_completion_date: str | None,
    special_instructions: str,
    drawing: UploadFile | None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    customer = await session.get(CustomerModel, customer_id)
    if customer is None:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="请选择有效客户。",
            status_code=404,
            details={"customer_id": customer_id},
        )

    if ensure_workspace_customer_credit_limit(customer):
        await session.flush()

    if quantity <= 0:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="数量必须大于 0。",
            status_code=400,
        )

    product = await ui_support.ensure_product_inventory(session, glass_type, thickness, quantity)
    request_payload = CreateOrderRequest(
        customer_id=customer.id,
        delivery_address=customer.address or "factory-pickup",
        expected_delivery_date=ui_support.parse_date_input(estimated_completion_date),
        priority=priority,
        remark=special_instructions,
        idempotency_key=idempotency_key,
        items=[
            CreateOrderItem(
                product_id=product.id,
                product_name=product.product_name,
                glass_type=glass_type.strip() or "Clear",
                specification=thickness.strip() or "6mm",
                width_mm=1000,
                height_mm=1000,
                quantity=quantity,
                unit_price=Decimal("1.00"),
                process_requirements=special_instructions,
            )
        ],
    )
    order_view = await orders_service.create_order(session, request_payload)

    if drawing is not None:
        payload_bytes = await drawing.read()
        if payload_bytes:
            await orders_service.upload_drawing(
                session,
                order_id=order_view.id,
                filename=drawing.filename or "drawing.pdf",
                payload_bytes=payload_bytes,
            )

    return {"order": await serialize_workspace_order(session, order_view.id, include_detail=True)}


async def update_workspace_order(
    session: AsyncSession,
    *,
    order_id: str,
    glass_type: str | None,
    thickness: str | None,
    quantity: int | None,
    priority: str | None,
    estimated_completion_date: str | None,
    special_instructions: str | None,
    drawing: UploadFile | None,
    actor_user_id: str,
) -> dict[str, Any]:
    order = await get_order_model(session, order_id, include_items=True)
    if not order.items:
        raise AppError(
            code=ErrorCode.ORDER_INVALID_TRANSITION,
            message="订单缺少明细，无法更新。",
            status_code=409,
            details={"order_id": order_id},
        )

    first_item = order.items[0]
    item_update = UpdateOrderItemRequest(id=first_item.id)

    if glass_type is not None:
        item_update.glass_type = glass_type.strip() or first_item.glass_type
    if thickness is not None:
        item_update.specification = thickness.strip() or first_item.specification
    if quantity is not None:
        if quantity <= 0:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="数量必须大于 0。",
                status_code=400,
            )
        item_update.quantity = quantity

    update_payload = UpdateOrderRequest(
        expected_delivery_date=(
            ui_support.parse_date_input(estimated_completion_date)
            if estimated_completion_date is not None
            else None
        ),
        priority=priority,
        remark=special_instructions,
        items=[item_update],
    )
    await orders_service.update_order(
        session,
        order_id=order_id,
        payload=update_payload,
        actor_user_id=actor_user_id,
    )

    if drawing is not None:
        payload_bytes = await drawing.read()
        if payload_bytes:
            await orders_service.upload_drawing(
                session,
                order_id=order_id,
                filename=drawing.filename or "drawing.pdf",
                payload_bytes=payload_bytes,
            )

    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}


async def cancel_workspace_order(
    session: AsyncSession,
    *,
    order_id: str,
    reason: str,
) -> dict[str, Any]:
    await orders_service.cancel_order(session, order_id=order_id, reason=reason)
    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}


async def mark_workspace_order_entered(
    session: AsyncSession,
    *,
    order_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    await orders_service.mark_entered(session, order_id=order_id, actor_user_id=actor_user_id)
    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}


async def apply_workspace_step_action(
    session: AsyncSession,
    *,
    order_id: str,
    step_key: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_role: str,
    actor_stage: str | None,
) -> dict[str, Any]:
    await orders_service.apply_step_action(
        session,
        order_id=order_id,
        step_key=step_key,
        action=str(payload.get("action") or "start"),
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        actor_stage=actor_stage,
        piece_numbers=normalize_piece_numbers(
            payload.get("pieceNumbers") or payload.get("piece_numbers") or []
        ),
        note=str(payload.get("note") or ""),
    )
    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}


async def approve_workspace_pickup(
    session: AsyncSession,
    *,
    order_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    await orders_service.approve_pickup(session, order_id=order_id, actor_user_id=actor_user_id)
    email_payload = await orders_service.send_pickup_email(
        session,
        order_id=order_id,
        actor_user_id=actor_user_id,
    )
    response = {"order": await serialize_workspace_order(session, order_id, include_detail=True)}
    response.update(email_payload)
    return response


async def send_workspace_pickup_email(
    session: AsyncSession,
    *,
    order_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    return await orders_service.send_pickup_email(
        session,
        order_id=order_id,
        actor_user_id=actor_user_id,
    )


async def save_workspace_pickup_signature(
    session: AsyncSession,
    *,
    order_id: str,
    signer_name: str,
    signature_data_url: str,
    actor_user_id: str,
) -> dict[str, Any]:
    await orders_service.save_pickup_signature(
        session,
        order_id=order_id,
        actor_user_id=actor_user_id,
        signer_name=signer_name,
        signature_data_url=signature_data_url,
    )
    return {"order": await serialize_workspace_order(session, order_id, include_detail=True)}
