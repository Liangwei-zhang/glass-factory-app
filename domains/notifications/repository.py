from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.notifications import NotificationModel


class NotificationsRepository:
    async def list_notifications(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 100,
        unread_only: bool = False,
    ) -> list[NotificationModel]:
        stmt = select(NotificationModel).where(NotificationModel.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationModel.is_read.is_(False))
        result = await session.execute(stmt.order_by(NotificationModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def mark_notifications_read(
        self,
        session: AsyncSession,
        user_id: str,
        notification_ids: list[str] | None = None,
    ) -> int:
        stmt = update(NotificationModel).where(
            NotificationModel.user_id == user_id,
            NotificationModel.is_read.is_(False),
        )

        if notification_ids:
            stmt = stmt.where(NotificationModel.id.in_(notification_ids))

        result = await session.execute(stmt.values(is_read=True))
        return int(result.rowcount or 0)
