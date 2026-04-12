from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.inventory import InventoryModel, InventoryReservationModel, ProductModel


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
            select(InventoryModel).where(InventoryModel.product_id == product_id).with_for_update()
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_inventory_for_update(
        self,
        session: AsyncSession,
        product_ids: list[str],
    ) -> list[InventoryModel]:
        if not product_ids:
            return []

        result = await session.execute(
            select(InventoryModel)
            .where(InventoryModel.product_id.in_(product_ids))
            .order_by(InventoryModel.product_id.asc())
            .with_for_update()
        )
        return list(result.scalars().all())

    async def get_inventory(self, session: AsyncSession, product_id: str) -> InventoryModel | None:
        result = await session.execute(
            select(InventoryModel).where(InventoryModel.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def list_reservations(
        self,
        session: AsyncSession,
        reservation_ids: list[str],
        *,
        for_update: bool = False,
    ) -> list[InventoryReservationModel]:
        if not reservation_ids:
            return []

        stmt = (
            select(InventoryReservationModel)
            .where(InventoryReservationModel.id.in_(reservation_ids))
            .order_by(InventoryReservationModel.created_at.asc())
        )
        if for_update:
            stmt = stmt.with_for_update()

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_expired_pending_reservations(
        self,
        session: AsyncSession,
        *,
        cutoff: datetime,
        limit: int,
    ) -> list[InventoryReservationModel]:
        result = await session.execute(
            select(InventoryReservationModel)
            .where(
                InventoryReservationModel.status == "pending",
                InventoryReservationModel.expires_at.is_not(None),
                InventoryReservationModel.expires_at <= cutoff,
            )
            .order_by(
                InventoryReservationModel.expires_at.asc(),
                InventoryReservationModel.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def get_product(self, session: AsyncSession, product_id: str) -> ProductModel | None:
        result = await session.execute(select(ProductModel).where(ProductModel.id == product_id))
        return result.scalar_one_or_none()
