from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.logistics import ShipmentModel


class LogisticsRepository:
    async def list_shipments(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        order_id: str | None = None,
    ) -> list[ShipmentModel]:
        stmt = select(ShipmentModel)
        if status:
            stmt = stmt.where(ShipmentModel.status == status)
        if order_id:
            stmt = stmt.where(ShipmentModel.order_id == order_id)
        result = await session.execute(stmt.order_by(ShipmentModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def get_tracking(self, session: AsyncSession, tracking_no: str) -> ShipmentModel | None:
        result = await session.execute(
            select(ShipmentModel).where(
                or_(ShipmentModel.tracking_no == tracking_no, ShipmentModel.shipment_no == tracking_no)
            )
        )
        return result.scalar_one_or_none()
