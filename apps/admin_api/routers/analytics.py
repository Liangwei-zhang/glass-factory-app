from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from infra.analytics.admin_analytics import AdminAnalyticsWarehouse
from infra.db.session import get_db_session
from infra.security.auth import AuthUser
from infra.security.rbac import require_roles

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_guard = require_roles(["admin", "manager"])
analytics_warehouse = AdminAnalyticsWarehouse()


@router.get("/overview")
async def analytics_overview(
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user
    return await analytics_warehouse.get_overview(session)


@router.get("/production")
async def analytics_production(
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user
    return await analytics_warehouse.get_production(session)


@router.get("/sales")
async def analytics_sales(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(admin_guard),
) -> dict:
    _ = user
    return await analytics_warehouse.get_sales(session, days=days)
