from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from domains.auth.schema import LoginRequest
from domains.auth.service import AuthService
from domains.workspace import settings_support, ui_support
from infra.cache.redis_client import get_redis
from infra.core.errors import AppError, ErrorCode
from infra.db.models.orders import OrderModel
from infra.db.models.settings import GlassTypeModel
from infra.db.models.users import UserModel
from infra.security.auth import AuthUser, create_access_token
from infra.security.identity import (
    can_create_orders,
    resolve_canonical_role,
    resolve_home_path,
    resolve_shell_name,
    resolve_stage_label,
    resolve_user_scopes,
)

REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
BOOTSTRAP_ACTIVE_ORDER_STATUSES = {
    "received",
    "entered",
    "in_production",
    "completed",
    "shipping",
    "ready_for_pickup",
}


def refresh_session_id(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def refresh_session_key(refresh_token: str) -> str:
    return f"session:{refresh_session_id(refresh_token)}"


def serialize_workspace_user(
    user: UserModel,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    canonical_role = resolve_canonical_role(user.role)
    resolved_scopes = resolve_user_scopes(
        user.role,
        scopes=list(user.scopes or []) if scopes is None else scopes,
        stage=user.stage,
    )
    return {
        "id": user.id,
        "name": user.display_name,
        "email": user.email,
        "role": canonical_role,
        "scopes": resolved_scopes,
        "customerId": user.customer_id,
        "stage": user.stage,
        "stageLabel": resolve_stage_label(user.stage),
        "canonicalRole": canonical_role,
        "homePath": resolve_home_path(user.role),
        "shell": resolve_shell_name(user.role),
        "canCreateOrders": can_create_orders(user.role),
    }


def build_workspace_summary(
    orders: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    *,
    role: str,
    stage: str | None,
) -> dict[str, Any]:
    summary = {
        "totalOrders": len(orders),
        "activeOrders": sum(
            1 for order in orders if order.get("status") in BOOTSTRAP_ACTIVE_ORDER_STATUSES
        ),
        "inProductionOrders": sum(1 for order in orders if order.get("status") == "in_production"),
        "readyForPickupOrders": sum(
            1 for order in orders if order.get("status") == "ready_for_pickup"
        ),
        "staleOrders": sum(1 for order in orders if bool(order.get("isStale"))),
        "rushOrders": sum(1 for order in orders if order.get("priority") == "rush"),
        "reworkOrders": sum(1 for order in orders if bool(order.get("reworkOpen"))),
        "modifiedOrders": sum(1 for order in orders if bool(order.get("isModified"))),
        "activeCustomers": sum(
            1 for customer in customers if bool(customer.get("hasActiveOrders"))
        ),
    }

    if resolve_canonical_role(role) == "operator" and stage:
        worker_orders = []
        for order in orders:
            step = next(
                (
                    candidate
                    for candidate in order.get("steps", [])
                    if candidate.get("key") == stage
                ),
                None,
            )
            if step and step.get("status") != "completed":
                worker_orders.append(order)

        summary["workerQueue"] = len(worker_orders)
        summary["workerReady"] = sum(
            1
            for order in worker_orders
            for step in order.get("steps", [])
            if step.get("key") == stage
            and (bool(step.get("isAvailable")) or step.get("status") == "in_progress")
        )

    return summary


async def get_workspace_user_model(session: AsyncSession, auth_user: AuthUser) -> UserModel:
    user = await session.get(UserModel, auth_user.user_id)
    if user is None:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="登录已失效，请重新登录。",
            status_code=401,
        )
    return user


async def login_workspace_user(
    session: AsyncSession,
    payload: dict[str, Any],
    service: AuthService | None = None,
) -> dict[str, Any]:
    principal = str(payload.get("email") or payload.get("username") or "").strip()
    password = str(payload.get("password") or "")

    if not principal or not password:
        raise AppError(
            code=ErrorCode.BAD_REQUEST,
            message="请输入邮箱和密码。",
            status_code=400,
        )

    auth_service = service or AuthService()
    login_result = await auth_service.login(
        session,
        LoginRequest(email=principal, password=password),
    )

    user_model = await session.get(UserModel, login_result.user.id)
    if user_model is None:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="登录已失效，请重新登录。",
            status_code=401,
        )

    resolved_scopes = resolve_user_scopes(
        user_model.role,
        scopes=login_result.user.scopes,
        stage=user_model.stage,
    )
    canonical_role = resolve_canonical_role(user_model.role)
    refresh_token = secrets.token_urlsafe(48)
    session_id = refresh_session_id(refresh_token)
    redis = await get_redis()
    await redis.set(
        refresh_session_key(refresh_token),
        json.dumps(
            {
                "user_id": user_model.id,
                "role": canonical_role,
                "scopes": resolved_scopes,
                "stage": user_model.stage,
                "customer_id": user_model.customer_id,
            }
        ),
        ex=REFRESH_TOKEN_TTL_SECONDS,
    )

    access_token = create_access_token(
        subject=user_model.id,
        role=canonical_role,
        scopes=resolved_scopes,
        stage=user_model.stage,
        customer_id=user_model.customer_id,
        session_id=session_id,
    )

    return {
        "token": access_token,
        "refreshToken": refresh_token,
        "user": serialize_workspace_user(user_model, resolved_scopes),
    }


async def build_workspace_me(
    session: AsyncSession,
    auth_user: AuthUser,
) -> dict[str, Any]:
    user_model = await get_workspace_user_model(session, auth_user)
    resolved_scopes = resolve_user_scopes(
        user_model.role,
        scopes=auth_user.scopes or user_model.scopes or [],
        stage=user_model.stage,
    )
    return {"user": serialize_workspace_user(user_model, resolved_scopes)}


async def build_workspace_bootstrap(
    session: AsyncSession,
    auth_user: AuthUser,
) -> dict[str, Any]:
    user_model = await get_workspace_user_model(session, auth_user)
    resolved_scopes = resolve_user_scopes(
        user_model.role,
        scopes=auth_user.scopes or user_model.scopes or [],
        stage=user_model.stage,
    )

    await ui_support.ensure_default_glass_types(session, user_model.id)
    await settings_support.ensure_pickup_template(session, user_model.id)

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
    order_rows = list(order_result.scalars().all())
    order_payloads = await ui_support.serialize_orders(
        session,
        order_rows,
        route_prefix="/v1/workspace",
    )

    customers = await ui_support.serialize_customers(session)
    notifications = await ui_support.serialize_notifications(session, user_model.id)
    summary = build_workspace_summary(
        order_payloads,
        customers,
        role=user_model.role,
        stage=user_model.stage,
    )

    return {
        "user": serialize_workspace_user(user_model, resolved_scopes),
        "options": {
            "glassTypes": glass_type_names,
            "thicknessOptions": ui_support.DEFAULT_THICKNESS_OPTIONS,
            "priorities": ui_support.DEFAULT_PRIORITIES,
            "orderStatuses": ui_support.DEFAULT_ORDER_STATUSES,
            "productionSteps": ui_support.PRODUCTION_STEPS,
        },
        "data": {
            "summary": summary,
            "customers": customers,
            "orders": order_payloads,
            "notifications": notifications,
        },
    }
