from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.events import EventOutboxModel
from infra.db.session import get_db_session
from infra.events.outbox import REPLAYABLE_OUTBOX_STATUSES, requeue_outbox_events
from infra.observability.metrics import (
    build_threshold_alerts,
    collect_runtime_snapshot,
    metrics_response,
)
from infra.observability.runtime_probe import run_runtime_probe
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/runtime", tags=["runtime"])
admin_guard = require_roles(["admin", "manager"])


class OutboxReplayRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=lambda: list(REPLAYABLE_OUTBOX_STATUSES))
    limit: int = Field(default=100, ge=1, le=1000)


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
    snapshot = await collect_runtime_snapshot(session)
    threshold_alerts = build_threshold_alerts(snapshot)

    result = await session.execute(
        select(EventOutboxModel)
        .where(EventOutboxModel.status.in_(["dead_letter", "failed"]))
        .order_by(EventOutboxModel.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    return {
        "items": (
            threshold_alerts
            + [
                {
                    "id": row.id,
                    "type": "event_outbox",
                    "topic": row.topic,
                    "event_key": row.event_key,
                    "status": row.status,
                    "replayable": row.status in REPLAYABLE_OUTBOX_STATUSES,
                    "attempt_count": row.attempt_count,
                    "max_attempts": row.max_attempts,
                    "last_error": row.last_error,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
        )[:limit]
    }


@router.post("/outbox/replay")
async def runtime_outbox_replay(
    payload: OutboxReplayRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user
    statuses = [status for status in payload.statuses if status]
    invalid_statuses = sorted(set(statuses) - set(REPLAYABLE_OUTBOX_STATUSES))
    if invalid_statuses:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_REPLAY_STATUS",
                "message": "Only failed and dead_letter events can be replayed.",
                "invalid_statuses": invalid_statuses,
            },
        )

    rows = await requeue_outbox_events(
        session,
        ids=payload.ids,
        statuses=statuses or list(REPLAYABLE_OUTBOX_STATUSES),
        limit=payload.limit,
    )
    await session.commit()

    replayed_ids = [row.id for row in rows]
    requested_ids = [event_id for event_id in payload.ids if event_id]
    missing_ids = sorted(set(requested_ids) - set(replayed_ids))
    return {
        "requested_statuses": statuses or list(REPLAYABLE_OUTBOX_STATUSES),
        "requested_ids": requested_ids,
        "replayed": len(replayed_ids),
        "replayed_ids": replayed_ids,
        "missing_ids": missing_ids,
    }
