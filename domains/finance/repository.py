from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.finance import ReceivableModel


class FinanceRepository:
    async def list_receivables(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        customer_id: str | None = None,
    ) -> list[ReceivableModel]:
        stmt = select(ReceivableModel)
        if status:
            stmt = stmt.where(ReceivableModel.status == status)
        if customer_id:
            stmt = stmt.where(ReceivableModel.customer_id == customer_id)
        result = await session.execute(stmt.order_by(ReceivableModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def list_statements(
        self,
        session: AsyncSession,
        limit: int = 100,
        customer_id: str | None = None,
    ) -> list[ReceivableModel]:
        stmt = select(ReceivableModel)
        if customer_id:
            stmt = stmt.where(ReceivableModel.customer_id == customer_id)
        result = await session.execute(stmt.order_by(ReceivableModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())

    async def list_invoices(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        customer_id: str | None = None,
    ) -> list[ReceivableModel]:
        stmt = select(ReceivableModel).where(ReceivableModel.invoice_no.is_not(None))
        if status:
            stmt = stmt.where(ReceivableModel.status == status)
        if customer_id:
            stmt = stmt.where(ReceivableModel.customer_id == customer_id)
        result = await session.execute(stmt.order_by(ReceivableModel.created_at.desc()).limit(limit))
        return list(result.scalars().all())
