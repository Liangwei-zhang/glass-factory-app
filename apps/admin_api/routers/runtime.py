from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel
from infra.db.session import get_db_session
from infra.observability.metrics import metrics_response
from infra.observability.runtime_probe import run_runtime_probe
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/runtime", tags=["runtime"])
admin_guard = require_roles(["admin", "manager"])


@router.get("/health")
async def runtime_health(user: AuthUser = Depends(admin_guard)) -> dict:
    _ = user
    return await run_runtime_probe()


@router.get("/probe")
async def runtime_probe(user: AuthUser = Depends(admin_guard)) -> dict:
    _ = user
    return await run_runtime_probe()


@router.get("/metrics", include_in_schema=False)
async def runtime_metrics(
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> Response:
    _ = user
    return await metrics_response(session)


@router.get("/alerts")
async def runtime_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user

    result = await session.execute(
        select(EventOutboxModel)
        .where(EventOutboxModel.status.in_(["dead_letter", "failed"]))
        .order_by(EventOutboxModel.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

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
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }
