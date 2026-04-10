from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from infra.observability.metrics import metrics_response

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()
