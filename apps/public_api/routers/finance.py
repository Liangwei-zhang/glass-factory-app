from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.finance.schema import (
    CreateReceivableRequest,
    InvoiceView,
    ReceivableView,
    RecordPaymentRequest,
    RecordRefundRequest,
    StatementView,
)
from domains.finance.service import FinanceService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key
from infra.security.rbac import require_scopes

router = APIRouter(prefix="/finance", tags=["finance"])
service = FinanceService()
write_guard = require_scopes(["finance:write"])


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


@router.post("/receivables", response_model=ReceivableView, status_code=201)
async def create_receivable(
    payload: CreateReceivableRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ReceivableView:
    await enforce_idempotency_key("finance:receivables:create", idempotency_key)
    return await service.create_receivable(session, payload, actor_user_id=user.user_id)


@router.post("/receivables/{receivable_id}/payments", response_model=ReceivableView)
async def record_payment(
    receivable_id: str,
    payload: RecordPaymentRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ReceivableView:
    await enforce_idempotency_key("finance:receivables:payments", idempotency_key)
    return await service.record_payment(
        session,
        receivable_id,
        payload,
        actor_user_id=user.user_id,
    )


@router.post("/receivables/{receivable_id}/refunds", response_model=ReceivableView)
async def record_refund(
    receivable_id: str,
    payload: RecordRefundRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(write_guard),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ReceivableView:
    await enforce_idempotency_key("finance:receivables:refunds", idempotency_key)
    return await service.record_refund(
        session,
        receivable_id,
        payload,
        actor_user_id=user.user_id,
    )
