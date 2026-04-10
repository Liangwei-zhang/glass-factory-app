from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.notifications import NotificationModel
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/operators", tags=["operators"])
admin_guard = require_roles(["admin", "supervisor", "manager"])


@router.get("")
async def list_operators(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    users_result = await session.execute(
        select(UserModel)
        .where(UserModel.role.in_(["operator", "worker"]))
        .order_by(UserModel.created_at.desc())
        .limit(limit)
    )
    operators = users_result.scalars().all()

    items = []
    for operator in operators:
        unread_count = await session.scalar(
            select(func.count(NotificationModel.id)).where(
                NotificationModel.user_id == operator.id,
                NotificationModel.is_read.is_(False),
            )
        )
        items.append(
            {
                "id": operator.id,
                "username": operator.username,
                "display_name": operator.display_name,
                "email": operator.email,
                "role": operator.role,
                "is_active": operator.is_active,
                "unread_notifications": int(unread_count or 0),
            }
        )

    return {"items": items}
