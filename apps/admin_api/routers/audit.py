from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/audit", tags=["audit"])
admin_guard = require_roles(["admin", "manager"])


@router.get("")
@router.get("/logs")
async def list_audit_logs(
    topic: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    stmt = select(EventOutboxModel)
    if topic:
        stmt = stmt.where(EventOutboxModel.topic == topic)
    if status:
        stmt = stmt.where(EventOutboxModel.status == status)

    result = await session.execute(stmt.order_by(EventOutboxModel.created_at.desc()).limit(limit))
    rows = result.scalars().all()

    dead_letter_count = await session.scalar(
        select(func.count(EventOutboxModel.id)).where(
            EventOutboxModel.status.in_(["dead_letter", "failed"])
        )
    )
    pending_count = await session.scalar(
        select(func.count(EventOutboxModel.id)).where(EventOutboxModel.status == "pending")
    )

    return {
        "items": [
            {
                "id": row.id,
                "topic": row.topic,
                "event_key": row.event_key,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "max_attempts": row.max_attempts,
                "last_error": row.last_error,
                "occurred_at": row.occurred_at,
                "published_at": row.published_at,
                "created_at": row.created_at,
                "payload": row.payload,
                "headers": row.headers,
            }
            for row in rows
        ],
        "summary": {
            "pending": int(pending_count or 0),
            "dead_letter": int(dead_letter_count or 0),
        },
    }
