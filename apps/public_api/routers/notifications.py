from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.notifications.schema import (
    MarkNotificationsReadRequest,
    MarkNotificationsReadResult,
    NotificationView,
)
from domains.notifications.service import NotificationsService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key

router = APIRouter(prefix="/notifications", tags=["notifications"])
service = NotificationsService()


@router.get("", response_model=list[NotificationView])
async def list_notifications(
    limit: int = Query(default=100, ge=1, le=500),
    unread_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[NotificationView]:
    return await service.list_notifications(
        session,
        user_id=user.user_id,
        limit=limit,
        unread_only=unread_only,
    )


@router.put("/read", response_model=MarkNotificationsReadResult)
async def mark_notifications_read(
    payload: MarkNotificationsReadRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MarkNotificationsReadResult:
    await enforce_idempotency_key("notifications:mark-read", idempotency_key)
    return await service.mark_notifications_read(
        session,
        user_id=user.user_id,
        notification_ids=payload.notification_ids,
    )
