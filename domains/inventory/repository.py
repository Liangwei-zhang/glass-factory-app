from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.inventory import InventoryModel, ProductModel


class InventoryRepository:
    async def list_inventory(
        self,
        session: AsyncSession,
        product_ids: list[str] | None = None,
    ) -> list[InventoryModel]:
        stmt = select(InventoryModel)
        if product_ids:
            stmt = stmt.where(InventoryModel.product_id.in_(product_ids))
        result = await session.execute(stmt.order_by(InventoryModel.updated_at.desc()))
        return list(result.scalars().all())

    async def get_inventory_for_update(
        self,
        session: AsyncSession,
        product_id: str,
    ) -> InventoryModel | None:
        stmt = (
            select(InventoryModel)
            .where(InventoryModel.product_id == product_id)
            .with_for_update()
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_inventory(self, session: AsyncSession, product_id: str) -> InventoryModel | None:
        result = await session.execute(
            select(InventoryModel).where(InventoryModel.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def get_product(self, session: AsyncSession, product_id: str) -> ProductModel | None:
        result = await session.execute(select(ProductModel).where(ProductModel.id == product_id))
        return result.scalar_one_or_none()
