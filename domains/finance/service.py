from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domains.finance.errors import ReceivableNotFound
from domains.finance.repository import FinanceRepository
from domains.finance.schema import (
    CreateReceivableRequest,
    InvoiceView,
    ReceivableView,
    RecordPaymentRequest,
    RecordRefundRequest,
    StatementView,
)
from infra.core.errors import AppError, ErrorCode
from infra.db.models.finance import ReceivableModel
from infra.db.models.orders import OrderModel
from infra.events.outbox import OutboxPublisher
from infra.events.topics import Topics


BILLABLE_ORDER_STATUSES = {"completed", "ready_for_pickup", "picked_up", "shipping", "delivered"}


class FinanceService:
    def __init__(self, repository: FinanceRepository | None = None) -> None:
        self.repository = repository or FinanceRepository()

    async def create_receivable(
        self,
        session: AsyncSession,
        payload: CreateReceivableRequest,
        *,
        actor_user_id: str,
    ) -> ReceivableView:
        order = await session.get(OrderModel, payload.order_id)
        if order is None:
            raise AppError(
                code=ErrorCode.ORDER_NOT_FOUND,
                message="Order not found.",
                status_code=404,
                details={"order_id": payload.order_id},
            )

        if order.status not in BILLABLE_ORDER_STATUSES:
            raise AppError(
                code=ErrorCode.ORDER_INVALID_TRANSITION,
                message="Order is not ready for settlement.",
                status_code=409,
                details={"order_id": order.id, "status": order.status},
            )

        amount = payload.amount or order.total_amount
        if amount <= Decimal("0"):
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Receivable amount must be greater than zero.",
                status_code=400,
            )

        row = await self.repository.get_receivable_by_order(session, order.id)
        if row is None:
            row = ReceivableModel(
                order_id=order.id,
                customer_id=order.customer_id,
                invoice_no=(payload.invoice_no or f"INV-{order.order_no}").strip() or None,
                amount=amount,
                paid_amount=Decimal("0"),
                status="unpaid",
                due_date=payload.due_date,
            )
            session.add(row)
        else:
            if row.paid_amount > amount:
                raise AppError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Receivable amount cannot be less than paid amount.",
                    status_code=409,
                    details={"receivable_id": row.id},
                )
            row.invoice_no = (payload.invoice_no or row.invoice_no or f"INV-{order.order_no}").strip() or None
            row.amount = amount
            row.due_date = payload.due_date
            if row.paid_amount == row.amount:
                row.status = "paid"
            elif row.paid_amount > Decimal("0"):
                row.status = "partial"
            else:
                row.status = "unpaid"

        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.FINANCE_INVOICE_CREATED,
            key=row.id,
            payload={
                "receivable_id": row.id,
                "order_id": row.order_id,
                "order_no": order.order_no,
                "customer_id": row.customer_id,
                "invoice_no": row.invoice_no,
                "amount": str(row.amount),
                "due_date": row.due_date.isoformat(),
                "status": row.status,
                "actor_user_id": actor_user_id,
            },
        )

        return ReceivableView.model_validate(row)

    async def record_payment(
        self,
        session: AsyncSession,
        receivable_id: str,
        payload: RecordPaymentRequest,
        *,
        actor_user_id: str,
    ) -> ReceivableView:
        row = await self.repository.get_receivable(session, receivable_id)
        if row is None:
            raise ReceivableNotFound(receivable_id)

        next_paid_amount = row.paid_amount + payload.amount
        if next_paid_amount > row.amount:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Payment exceeds receivable amount.",
                status_code=409,
                details={"receivable_id": row.id},
            )

        row.paid_amount = next_paid_amount
        row.status = "paid" if row.paid_amount == row.amount else "partial"
        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.FINANCE_PAYMENT_RECEIVED,
            key=row.id,
            payload={
                "receivable_id": row.id,
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "amount": str(payload.amount),
                "paid_amount": str(row.paid_amount),
                "status": row.status,
                "actor_user_id": actor_user_id,
            },
        )

        return ReceivableView.model_validate(row)

    async def record_refund(
        self,
        session: AsyncSession,
        receivable_id: str,
        payload: RecordRefundRequest,
        *,
        actor_user_id: str,
    ) -> ReceivableView:
        row = await self.repository.get_receivable(session, receivable_id)
        if row is None:
            raise ReceivableNotFound(receivable_id)

        if payload.amount > row.paid_amount:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Refund exceeds paid amount.",
                status_code=409,
                details={"receivable_id": row.id},
            )

        row.paid_amount = row.paid_amount - payload.amount
        if row.paid_amount == row.amount:
            row.status = "paid"
        elif row.paid_amount > Decimal("0"):
            row.status = "partial"
        else:
            row.status = "unpaid"
        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.FINANCE_PAYMENT_REFUNDED,
            key=row.id,
            payload={
                "receivable_id": row.id,
                "order_id": row.order_id,
                "customer_id": row.customer_id,
                "amount": str(payload.amount),
                "paid_amount": str(row.paid_amount),
                "status": row.status,
                "actor_user_id": actor_user_id,
            },
        )

        return ReceivableView.model_validate(row)

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
