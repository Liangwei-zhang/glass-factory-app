from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.core.errors import AppError
from infra.db.models.customers import CustomerModel
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.identity import (
    CUSTOMER_ROLES,
    normalize_role,
    resolve_canonical_role,
    resolve_home_path,
    resolve_shell_name,
    resolve_user_scopes,
)
from infra.security.rbac import require_roles

router = APIRouter(prefix="/users", tags=["users"])
admin_guard = require_roles(["admin", "manager"])


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name: str | None = None
    role: str | None = None
    scopes: list[str] | None = None
    is_active: bool | None = None
    stage: str | None = None
    customer_id: str | None = Field(default=None, alias="customerId")


class BulkUserActionRequest(BaseModel):
    action: str = Field(description="activate | deactivate | set_role")
    user_ids: list[str] = Field(min_length=1)
    role: str | None = None


def _serialize_user_row(row: UserModel, customer_name: str | None = None) -> dict:
    resolved_scopes = resolve_user_scopes(row.role, scopes=row.scopes, stage=row.stage)
    return {
        "id": row.id,
        "username": row.username,
        "email": row.email,
        "display_name": row.display_name,
        "role": row.role,
        "canonicalRole": resolve_canonical_role(row.role),
        "scopes": resolved_scopes,
        "stage": row.stage,
        "customerId": row.customer_id,
        "customerName": customer_name,
        "homePath": resolve_home_path(row.role),
        "shell": resolve_shell_name(row.role),
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("")
async def list_users(
    role: str | None = Query(default=None),
    customer_id: str | None = Query(default=None, alias="customerId"),
    stage: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    stmt = select(UserModel, CustomerModel.company_name).outerjoin(
        CustomerModel, CustomerModel.id == UserModel.customer_id
    )
    if role:
        stmt = stmt.where(UserModel.role == role)
    if customer_id:
        stmt = stmt.where(UserModel.customer_id == customer_id)
    if stage:
        stmt = stmt.where(UserModel.stage == stage)

    result = await session.execute(stmt.order_by(UserModel.created_at.desc()).limit(limit))
    rows = result.all()

    return {"items": [_serialize_user_row(row, customer_name) for row, customer_name in rows]}


@router.put("/{user_id}")
async def update_user(
    payload: UpdateUserRequest,
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    row = await session.get(UserModel, user_id)
    if row is None:
        raise AppError(
            code="USER_NOT_FOUND",
            message=f"User not found: {user_id}",
            status_code=404,
        )

    provided_fields = set(payload.model_fields_set)

    next_role = row.role
    if "role" in provided_fields:
        next_role = str(payload.role or "").strip()
        if not next_role:
            raise AppError(
                code="INVALID_USER_ROLE",
                message="role cannot be empty.",
                status_code=400,
            )

    next_customer_id = row.customer_id
    if "customer_id" in provided_fields:
        next_customer_id = str(payload.customer_id or "").strip() or None
    elif "role" in provided_fields and normalize_role(next_role) not in CUSTOMER_ROLES:
        next_customer_id = None

    customer_name = None
    if next_customer_id:
        customer = await session.get(CustomerModel, next_customer_id)
        if customer is None:
            raise AppError(
                code="CUSTOMER_NOT_FOUND",
                message=f"Customer not found: {next_customer_id}",
                status_code=404,
            )
        customer_name = customer.company_name

    if normalize_role(next_role) in CUSTOMER_ROLES and not next_customer_id:
        raise AppError(
            code="CUSTOMER_LINK_REQUIRED",
            message="customerId is required for customer and customer_viewer roles.",
            status_code=400,
        )

    next_stage = row.stage
    if "stage" in provided_fields:
        next_stage = str(payload.stage or "").strip() or None
    elif "role" in provided_fields and resolve_canonical_role(next_role) != "operator":
        next_stage = None

    if "display_name" in provided_fields:
        row.display_name = payload.display_name or row.display_name
    if "scopes" in provided_fields:
        row.scopes = payload.scopes or []
    if "is_active" in provided_fields and payload.is_active is not None:
        row.is_active = payload.is_active

    row.role = next_role
    row.customer_id = next_customer_id
    row.stage = next_stage

    await session.flush()

    return _serialize_user_row(row, customer_name)


@router.post("/bulk")
async def bulk_user_action(
    payload: BulkUserActionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    action = payload.action.strip().lower()
    if action == "activate":
        stmt = update(UserModel).where(UserModel.id.in_(payload.user_ids)).values(is_active=True)
    elif action == "deactivate":
        stmt = update(UserModel).where(UserModel.id.in_(payload.user_ids)).values(is_active=False)
    elif action == "set_role":
        if not payload.role:
            raise AppError(
                code="INVALID_BULK_ACTION",
                message="role is required when action is set_role",
                status_code=400,
            )
        next_role = payload.role.strip()
        if normalize_role(next_role) in CUSTOMER_ROLES:
            raise AppError(
                code="INVALID_BULK_ACTION",
                message="Use single-user update to assign customer roles with customerId.",
                status_code=400,
            )
        values = {"role": next_role, "customer_id": None}
        if resolve_canonical_role(next_role) != "operator":
            values["stage"] = None
        stmt = update(UserModel).where(UserModel.id.in_(payload.user_ids)).values(**values)
    else:
        raise AppError(
            code="INVALID_BULK_ACTION",
            message=f"Unsupported bulk action: {payload.action}",
            status_code=400,
        )

    result = await session.execute(stmt)

    rows_result = await session.execute(
        select(UserModel, CustomerModel.company_name)
        .outerjoin(CustomerModel, CustomerModel.id == UserModel.customer_id)
        .where(UserModel.id.in_(payload.user_ids))
    )
    rows = rows_result.all()

    return {
        "affected_count": int(result.rowcount or 0),
        "items": [_serialize_user_row(row, customer_name) for row, customer_name in rows],
    }
