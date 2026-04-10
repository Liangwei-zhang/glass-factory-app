from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domains.logistics.repository import LogisticsRepository
from domains.logistics.schema import ShipmentView
from infra.core.errors import AppError, ErrorCode


class LogisticsService:
    def __init__(self, repository: LogisticsRepository | None = None) -> None:
        self.repository = repository or LogisticsRepository()

    async def list_shipments(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        order_id: str | None = None,
    ) -> list[ShipmentView]:
        rows = await self.repository.list_shipments(
            session,
            limit=limit,
            status=status,
            order_id=order_id,
        )
        return [ShipmentView.model_validate(row) for row in rows]

    async def get_tracking(self, session: AsyncSession, tracking_no: str) -> ShipmentView:
        row = await self.repository.get_tracking(session, tracking_no=tracking_no)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Shipment tracking not found.",
                status_code=404,
                details={"tracking_no": tracking_no},
            )
        return ShipmentView.model_validate(row)
