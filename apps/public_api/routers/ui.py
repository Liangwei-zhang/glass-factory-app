from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

PUBLIC_DIR = Path(__file__).resolve().parents[3] / "public"
INDEX_HTML = PUBLIC_DIR / "index.html"

router = APIRouter(tags=["ui"])


def _spa_index_response() -> FileResponse:
    return FileResponse(path=INDEX_HTML)


@router.get("/app", response_class=FileResponse, include_in_schema=False)
async def app_shell() -> FileResponse:
    return _spa_index_response()


@router.get("/platform", response_class=FileResponse, include_in_schema=False)
async def platform_shell() -> FileResponse:
    return _spa_index_response()


@router.get("/admin", response_class=FileResponse, include_in_schema=False)
async def admin_shell() -> FileResponse:
    return _spa_index_response()
