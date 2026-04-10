from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory.schema import InventorySnapshot
from domains.inventory.service import InventoryService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user

router = APIRouter(prefix="/inventory", tags=["inventory"])
service = InventoryService()


@router.get("", response_model=list[InventorySnapshot])
async def list_inventory(
    product_ids: list[str] | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[InventorySnapshot]:
    _ = user
    return await service.list_inventory(session, product_ids=product_ids)


@router.get("/{product_id}", response_model=InventorySnapshot)
async def get_inventory_item(
    product_id: str,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> InventorySnapshot:
    _ = user
    return await service.get_inventory_item(session, product_id=product_id)
