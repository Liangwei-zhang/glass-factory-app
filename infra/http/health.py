from __future__ import annotations

from fastapi import APIRouter

from infra.observability.runtime_probe import run_runtime_probe

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> dict:
    return await run_runtime_probe()
