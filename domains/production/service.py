from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from domains.production.repository import ProductionRepository
from domains.production.schema import ProductionLineView, WorkOrderView


class ProductionService:
    def __init__(self, repository: ProductionRepository | None = None) -> None:
        self.repository = repository or ProductionRepository()

    async def list_work_orders(
        self,
        session: AsyncSession,
        limit: int = 100,
        step_key: str | None = None,
        assignee_user_id: str | None = None,
        include_unassigned: bool = False,
    ) -> list[WorkOrderView]:
        rows = await self.repository.list_work_orders(
            session,
            limit=limit,
            step_key=step_key,
            assignee_user_id=assignee_user_id,
            include_unassigned=include_unassigned,
        )
        return [WorkOrderView.model_validate(row) for row in rows]

    async def list_lines(
        self,
        session: AsyncSession,
        limit: int = 100,
        active_only: bool = False,
    ) -> list[ProductionLineView]:
        rows = await self.repository.list_lines(session, limit=limit, active_only=active_only)
        return [ProductionLineView.model_validate(row) for row in rows]

    async def get_work_order(
        self, session: AsyncSession, work_order_id: str
    ) -> WorkOrderView | None:
        row = await self.repository.get_work_order(session, work_order_id)
        if row is None:
            return None
        return WorkOrderView.model_validate(row)

    async def list_schedule(
        self,
        session: AsyncSession,
        day: date | None = None,
        limit: int = 100,
        step_key: str | None = None,
        assignee_user_id: str | None = None,
        include_unassigned: bool = False,
    ) -> list[WorkOrderView]:
        rows = await self.repository.list_schedule(
            session,
            day=day,
            limit=limit,
            step_key=step_key,
            assignee_user_id=assignee_user_id,
            include_unassigned=include_unassigned,
        )
        return [WorkOrderView.model_validate(row) for row in rows]
