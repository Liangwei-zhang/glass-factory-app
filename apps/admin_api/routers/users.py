from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.core.errors import AppError
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/users", tags=["users"])
admin_guard = require_roles(["admin", "supervisor", "manager"])


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    scopes: list[str] | None = None
    is_active: bool | None = None


class BulkUserActionRequest(BaseModel):
    action: str = Field(description="activate | deactivate | set_role")
    user_ids: list[str] = Field(min_length=1)
    role: str | None = None


@router.get("")
async def list_users(
    role: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    stmt = select(UserModel)
    if role:
        stmt = stmt.where(UserModel.role == role)

    result = await session.execute(stmt.order_by(UserModel.created_at.desc()).limit(limit))
    rows = result.scalars().all()

    return {
        "items": [
            {
                "id": row.id,
                "username": row.username,
                "email": row.email,
                "display_name": row.display_name,
                "role": row.role,
                "scopes": row.scopes,
                "is_active": row.is_active,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


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

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    await session.flush()

    return {
        "id": row.id,
        "username": row.username,
        "email": row.email,
        "display_name": row.display_name,
        "role": row.role,
        "scopes": row.scopes,
        "is_active": row.is_active,
        "updated_at": row.updated_at,
    }


@router.post("/bulk")
async def bulk_user_action(
    payload: BulkUserActionRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    action = payload.action.strip().lower()
    if action == "activate":
        stmt = (
            update(UserModel)
            .where(UserModel.id.in_(payload.user_ids))
            .values(is_active=True)
        )
    elif action == "deactivate":
        stmt = (
            update(UserModel)
            .where(UserModel.id.in_(payload.user_ids))
            .values(is_active=False)
        )
    elif action == "set_role":
        if not payload.role:
            raise AppError(
                code="INVALID_BULK_ACTION",
                message="role is required when action is set_role",
                status_code=400,
            )
        stmt = (
            update(UserModel)
            .where(UserModel.id.in_(payload.user_ids))
            .values(role=payload.role)
        )
    else:
        raise AppError(
            code="INVALID_BULK_ACTION",
            message=f"Unsupported bulk action: {payload.action}",
            status_code=400,
        )

    result = await session.execute(stmt)

    rows_result = await session.execute(
        select(UserModel).where(UserModel.id.in_(payload.user_ids))
    )
    rows = rows_result.scalars().all()

    return {
        "affected_count": int(result.rowcount or 0),
        "items": [
            {
                "id": row.id,
                "username": row.username,
                "role": row.role,
                "is_active": row.is_active,
            }
            for row in rows
        ],
    }
