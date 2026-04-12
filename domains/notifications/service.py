from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domains.notifications.repository import NotificationsRepository
from domains.notifications.schema import MarkNotificationsReadResult, NotificationView


class NotificationsService:
    def __init__(self, repository: NotificationsRepository | None = None) -> None:
        self.repository = repository or NotificationsRepository()

    async def list_notifications(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 100,
        unread_only: bool = False,
    ) -> list[NotificationView]:
        rows = await self.repository.list_notifications(
            session,
            user_id=user_id,
            limit=limit,
            unread_only=unread_only,
        )
        return [NotificationView.model_validate(row) for row in rows]

    async def mark_notifications_read(
        self,
        session: AsyncSession,
        user_id: str,
        notification_ids: list[str] | None = None,
    ) -> MarkNotificationsReadResult:
        updated_count = await self.repository.mark_notifications_read(
            session,
            user_id=user_id,
            notification_ids=notification_ids,
        )
        return MarkNotificationsReadResult(updated_count=updated_count)
