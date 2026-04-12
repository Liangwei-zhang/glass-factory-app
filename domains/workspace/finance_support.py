from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domains.finance.schema import (
    CreateReceivableRequest,
    ReceivableView,
    RecordPaymentRequest,
    RecordRefundRequest,
)
from domains.finance.service import FinanceService

service = FinanceService()


def _serialize_receivable(view: ReceivableView) -> dict[str, Any]:
    return view.model_dump(mode="json")


async def list_workspace_receivables(
    session: AsyncSession,
    *,
    limit: int = 100,
    status: str | None = None,
    customer_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = await service.list_receivables(
        session,
        limit=limit,
        status=status,
        customer_id=customer_id,
    )
    return [_serialize_receivable(row) for row in rows]


async def create_workspace_receivable(
    session: AsyncSession,
    *,
    order_id: str,
    due_date,
    amount,
    invoice_no: str | None,
    actor_user_id: str,
) -> dict[str, Any]:
    receivable = await service.create_receivable(
        session,
        CreateReceivableRequest(
            order_id=order_id,
            due_date=due_date,
            amount=amount,
            invoice_no=invoice_no,
        ),
        actor_user_id=actor_user_id,
    )
    return {"receivable": _serialize_receivable(receivable)}


async def record_workspace_payment(
    session: AsyncSession,
    *,
    receivable_id: str,
    amount,
    actor_user_id: str,
) -> dict[str, Any]:
    receivable = await service.record_payment(
        session,
        receivable_id,
        RecordPaymentRequest(amount=amount),
        actor_user_id=actor_user_id,
    )
    return {"receivable": _serialize_receivable(receivable)}


async def record_workspace_refund(
    session: AsyncSession,
    *,
    receivable_id: str,
    amount,
    actor_user_id: str,
) -> dict[str, Any]:
    receivable = await service.record_refund(
        session,
        receivable_id,
        RecordRefundRequest(amount=amount),
        actor_user_id=actor_user_id,
    )
    return {"receivable": _serialize_receivable(receivable)}
