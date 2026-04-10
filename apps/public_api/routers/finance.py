from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.finance.schema import InvoiceView, ReceivableView, StatementView
from domains.finance.service import FinanceService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user

router = APIRouter(prefix="/finance", tags=["finance"])
service = FinanceService()


@router.get("/receivables", response_model=list[ReceivableView])
async def list_receivables(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[ReceivableView]:
    _ = user
    return await service.list_receivables(
        session,
        limit=limit,
        status=status,
        customer_id=customer_id,
    )


@router.get("/statements", response_model=list[StatementView])
async def list_statements(
    limit: int = Query(default=100, ge=1, le=500),
    customer_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[StatementView]:
    _ = user
    return await service.list_statements(session, limit=limit, customer_id=customer_id)


@router.get("/invoices", response_model=list[InvoiceView])
async def list_invoices(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    customer_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[InvoiceView]:
    _ = user
    return await service.list_invoices(
        session,
        limit=limit,
        status=status,
        customer_id=customer_id,
    )
