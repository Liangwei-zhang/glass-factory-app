from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domains.workspace import ui_support
from infra.core.errors import AppError, ErrorCode
from infra.db.models.orders import OrderItemModel, OrderModel
from infra.db.models.settings import EmailLogModel, GlassTypeModel, NotificationTemplateModel
from infra.db.models.users import UserModel

PICKUP_TEMPLATE_KEY = "ready_for_pickup"
DEFAULT_TEMPLATE = {
    "name": "Ready for Pickup 邮件",
    "subject_template": "订单 {{orderNo}} 已可取货",
    "body_template": "您好 {{customerName}}，\n\n订单 {{orderNo}} 已可取货。\n玻璃类型：{{glassType}}\n规格：{{specification}}\n数量：{{quantity}}\n\n请安排到厂取货。\n",
}
AVAILABLE_TEMPLATE_VARIABLES = [
    "customerName",
    "orderNo",
    "glassType",
    "specification",
    "quantity",
]


def serialize_glass_type(glass_type: GlassTypeModel) -> dict[str, Any]:
    return {
        "id": glass_type.id,
        "name": glass_type.name,
        "isActive": bool(glass_type.is_active),
        "sortOrder": glass_type.sort_order,
        "totalOrderCount": 0,
        "activeOrderCount": 0,
        "updatedAt": glass_type.updated_at,
        "updatedByName": "",
    }


def serialize_notification_template(
    template: NotificationTemplateModel,
    updated_by_name: str | None,
) -> dict[str, Any]:
    return {
        "templateKey": template.template_key,
        "name": template.name,
        "subjectTemplate": template.subject_template,
        "bodyTemplate": template.body_template,
        "availableVariables": AVAILABLE_TEMPLATE_VARIABLES,
        "updatedAt": template.updated_at,
        "updatedByName": updated_by_name or "",
    }


def serialize_email_log(log: EmailLogModel, order_no: str | None = None) -> dict[str, Any]:
    return {
        "id": log.id,
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


async def ensure_pickup_template(
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


async def _resolve_updated_user_name(
    session: AsyncSession,
    user_id: str | None,
) -> str:
    if not user_id:
        return ""
    updated_user = await session.get(UserModel, user_id)
    return updated_user.display_name if updated_user else ""


async def list_glass_types(
    session: AsyncSession,
    actor_user_id: str | None = None,
) -> list[dict[str, Any]]:
    await ui_support.ensure_default_glass_types(session, actor_user_id)
    result = await session.execute(
        select(GlassTypeModel).order_by(GlassTypeModel.sort_order.asc(), GlassTypeModel.name.asc())
    )
    return [serialize_glass_type(row) for row in result.scalars().all()]


async def create_glass_type(
    session: AsyncSession,
    *,
    name: str,
    actor_user_id: str,
) -> GlassTypeModel:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="玻璃类型名称不能为空。",
            status_code=400,
        )
    if len(normalized_name) > 64:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="玻璃类型名称不能超过 64 个字符。",
            status_code=400,
        )

    duplicate = await session.execute(
        select(GlassTypeModel).where(func.lower(GlassTypeModel.name) == normalized_name.lower())
    )
    if duplicate.scalar_one_or_none() is not None:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="玻璃类型已存在。",
            status_code=409,
        )

    max_sort_order = await session.scalar(
        select(func.coalesce(func.max(GlassTypeModel.sort_order), -1))
    )
    glass_type = GlassTypeModel(
        name=normalized_name,
        is_active=True,
        sort_order=int(max_sort_order or -1) + 1,
        updated_at=datetime.now(timezone.utc),
        updated_by=actor_user_id,
    )
    session.add(glass_type)
    await session.flush()
    return glass_type


async def update_glass_type(
    session: AsyncSession,
    glass_type_id: str,
    *,
    name: str | None = None,
    is_active: bool | None = None,
    actor_user_id: str,
) -> GlassTypeModel:
    row = await session.get(GlassTypeModel, glass_type_id)
    if row is None:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="玻璃类型不存在。",
            status_code=404,
            details={"glass_type_id": glass_type_id},
        )

    original_name = row.name
    if name is not None:
        next_name = str(name or "").strip()
        if not next_name:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="玻璃类型名称不能为空。",
                status_code=400,
            )
        if len(next_name) > 64:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="玻璃类型名称不能超过 64 个字符。",
                status_code=400,
            )
        duplicate = await session.execute(
            select(GlassTypeModel)
            .where(func.lower(GlassTypeModel.name) == next_name.lower())
            .where(GlassTypeModel.id != row.id)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="玻璃类型已存在。",
                status_code=409,
            )

        row.name = next_name
        await session.execute(
            update(OrderItemModel)
            .where(func.lower(OrderItemModel.glass_type) == original_name.lower())
            .values(glass_type=next_name)
        )

    if is_active is not None:
        row.is_active = is_active

    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = actor_user_id
    await session.flush()
    return row


async def get_notification_template(
    session: AsyncSession,
    template_key: str,
    actor_user_id: str,
) -> dict[str, Any]:
    if template_key != PICKUP_TEMPLATE_KEY:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="模板不存在。",
            status_code=404,
            details={"template_key": template_key},
        )

    template = await ensure_pickup_template(session, actor_user_id)
    updated_by_name = await _resolve_updated_user_name(session, template.updated_by)
    return serialize_notification_template(template, updated_by_name)


async def update_notification_template(
    session: AsyncSession,
    template_key: str,
    *,
    subject_template: str,
    body_template: str,
    actor_user_id: str,
) -> dict[str, Any]:
    if template_key != PICKUP_TEMPLATE_KEY:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="模板不存在。",
            status_code=404,
            details={"template_key": template_key},
        )

    normalized_subject = str(subject_template or "").strip()
    normalized_body = str(body_template or "").strip()
    if not normalized_subject:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="标题模板不能为空。",
            status_code=400,
        )
    if not normalized_body:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="正文模板不能为空。",
            status_code=400,
        )

    template = await ensure_pickup_template(session, actor_user_id)
    template.subject_template = normalized_subject
    template.body_template = normalized_body
    template.updated_at = datetime.now(timezone.utc)
    template.updated_by = actor_user_id
    await session.flush()

    updated_by_name = await _resolve_updated_user_name(session, actor_user_id)
    return serialize_notification_template(template, updated_by_name)


async def list_email_logs(
    session: AsyncSession,
    limit: int = 20,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(EmailLogModel).order_by(EmailLogModel.created_at.desc()).limit(limit)
    )
    logs = list(result.scalars().all())

    order_map: dict[str, str] = {}
    order_ids = [entry.order_id for entry in logs if entry.order_id]
    if order_ids:
        order_result = await session.execute(
            select(OrderModel.id, OrderModel.order_no).where(OrderModel.id.in_(order_ids))
        )
        order_map = {row_id: order_no for row_id, order_no in order_result.all()}

    return [serialize_email_log(log, order_map.get(log.order_id or "")) for log in logs]
