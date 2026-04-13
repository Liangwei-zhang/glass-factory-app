from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.session import get_db_session
from infra.observability.metrics import metrics_response

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/metrics", include_in_schema=False)
async def metrics(session: AsyncSession = Depends(get_db_session)) -> Response:
    return await metrics_response(session)
