from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

PUBLIC_DIR = Path(__file__).resolve().parents[3] / "public"
APP_HTML = PUBLIC_DIR / "app.html"
PLATFORM_HTML = PUBLIC_DIR / "platform.html"
ADMIN_HTML = PUBLIC_DIR / "admin.html"

router = APIRouter(tags=["ui"])


def _shell_response(path: Path) -> FileResponse:
    return FileResponse(path=path)


@router.get("/app", response_class=FileResponse, include_in_schema=False)
async def app_shell() -> FileResponse:
    return _shell_response(APP_HTML)


@router.get("/platform", response_class=FileResponse, include_in_schema=False)
async def platform_shell() -> FileResponse:
    return _shell_response(PLATFORM_HTML)


@router.get("/admin", response_class=FileResponse, include_in_schema=False)
async def admin_shell() -> FileResponse:
    return _shell_response(ADMIN_HTML)
