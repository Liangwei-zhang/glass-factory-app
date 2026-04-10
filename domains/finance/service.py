from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domains.finance.repository import FinanceRepository
from domains.finance.schema import InvoiceView, ReceivableView, StatementView


class FinanceService:
    def __init__(self, repository: FinanceRepository | None = None) -> None:
        self.repository = repository or FinanceRepository()

    async def list_receivables(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        customer_id: str | None = None,
    ) -> list[ReceivableView]:
        rows = await self.repository.list_receivables(
            session,
            limit=limit,
            status=status,
            customer_id=customer_id,
        )
        return [ReceivableView.model_validate(row) for row in rows]

    async def list_statements(
        self,
        session: AsyncSession,
        limit: int = 100,
        customer_id: str | None = None,
    ) -> list[StatementView]:
        rows = await self.repository.list_statements(
            session,
            limit=limit,
            customer_id=customer_id,
        )
        return [StatementView.model_validate(row) for row in rows]

    async def list_invoices(
        self,
        session: AsyncSession,
        limit: int = 100,
        status: str | None = None,
        customer_id: str | None = None,
    ) -> list[InvoiceView]:
        rows = await self.repository.list_invoices(
            session,
            limit=limit,
            status=status,
            customer_id=customer_id,
        )
        return [InvoiceView.model_validate(row) for row in rows]
