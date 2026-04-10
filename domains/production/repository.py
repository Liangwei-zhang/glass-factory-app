from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.production import ProductionLineModel, WorkOrderModel


class ProductionRepository:
    async def list_work_orders(
        self,
        session: AsyncSession,
        limit: int = 100,
        step_key: str | None = None,
        assignee_user_id: str | None = None,
        include_unassigned: bool = False,
    ) -> list[WorkOrderModel]:
        stmt = select(WorkOrderModel)
        if step_key:
            stmt = stmt.where(WorkOrderModel.process_step_key == step_key)
        if assignee_user_id:
            if include_unassigned:
                stmt = stmt.where(
                    or_(
                        WorkOrderModel.assigned_user_id == assignee_user_id,
                        WorkOrderModel.assigned_user_id.is_(None),
                    )
                )
            else:
                stmt = stmt.where(WorkOrderModel.assigned_user_id == assignee_user_id)

        result = await session.execute(stmt.order_by(WorkOrderModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def list_lines(
        self,
        session: AsyncSession,
        limit: int = 100,
        active_only: bool = False,
    ) -> list[ProductionLineModel]:
        stmt = (
            select(ProductionLineModel).order_by(ProductionLineModel.line_code.asc()).limit(limit)
        )
        if active_only:
            stmt = stmt.where(ProductionLineModel.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_work_order(
        self, session: AsyncSession, work_order_id: str
    ) -> WorkOrderModel | None:
        result = await session.execute(
            select(WorkOrderModel).where(WorkOrderModel.id == work_order_id)
        )
        return result.scalar_one_or_none()

    async def list_schedule(
        self,
        session: AsyncSession,
        day: date | None = None,
        limit: int = 100,
        step_key: str | None = None,
        assignee_user_id: str | None = None,
        include_unassigned: bool = False,
    ) -> list[WorkOrderModel]:
        stmt = select(WorkOrderModel).where(WorkOrderModel.scheduled_date.is_not(None))
        if day is not None:
            stmt = stmt.where(WorkOrderModel.scheduled_date == day)
        if step_key:
            stmt = stmt.where(WorkOrderModel.process_step_key == step_key)
        if assignee_user_id:
            if include_unassigned:
                stmt = stmt.where(
                    or_(
                        WorkOrderModel.assigned_user_id == assignee_user_id,
                        WorkOrderModel.assigned_user_id.is_(None),
                    )
                )
            else:
                stmt = stmt.where(WorkOrderModel.assigned_user_id == assignee_user_id)

        result = await session.execute(
            stmt.order_by(
                WorkOrderModel.scheduled_date.asc(), WorkOrderModel.created_at.asc()
            ).limit(limit)
        )
        return list(result.scalars().all())
