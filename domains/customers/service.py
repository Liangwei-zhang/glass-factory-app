from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.errors import CustomerCreditExceeded
from domains.customers.repository import CustomersRepository
from domains.customers.schema import (
    CreateCustomerRequest,
    CreditCheckResult,
    CustomerCreditBalance,
    CustomerProfile,
)
from infra.core.errors import AppError, ErrorCode


class CustomersService:
    def __init__(self, repository: CustomersRepository | None = None) -> None:
        self.repository = repository or CustomersRepository()

    async def list_customers(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> list[CustomerProfile]:
        rows = await self.repository.list_customers(session, limit=limit)
        return [CustomerProfile.model_validate(row) for row in rows]

    async def create_customer(
        self,
        session: AsyncSession,
        payload: CreateCustomerRequest,
    ) -> CustomerProfile:
        row = await self.repository.create_customer(session, payload)
        return CustomerProfile.model_validate(row)

    async def get_customer_profile(self, session: AsyncSession, customer_id: str) -> CustomerProfile:
        row = await self.repository.get_customer(session, customer_id)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Customer not found.",
                status_code=404,
                details={"customer_id": customer_id},
            )
        return CustomerProfile.model_validate(row)

    async def get_credit_balance(self, session: AsyncSession, customer_id: str) -> CustomerCreditBalance:
        row = await self.repository.get_customer(session, customer_id)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Customer not found.",
                status_code=404,
                details={"customer_id": customer_id},
            )

        available = row.credit_limit - row.credit_used
        return CustomerCreditBalance(
            customer_id=row.id,
            credit_limit=row.credit_limit,
            credit_used=row.credit_used,
            available_credit=available,
        )

    async def check_credit(
        self,
        session: AsyncSession,
        customer_id: str,
        amount: Decimal,
    ) -> CreditCheckResult:
        customer = await self.repository.get_customer(session, customer_id)
        if customer is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Customer not found.",
                status_code=404,
                details={"customer_id": customer_id},
            )

        available = customer.credit_limit - customer.credit_used
        allowed = available >= amount
        if not allowed:
            raise CustomerCreditExceeded(customer_id, amount, available)

        return CreditCheckResult(
            allowed=allowed,
            credit_limit=customer.credit_limit,
            credit_used=customer.credit_used,
            available_credit=available,
        )
