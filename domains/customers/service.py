from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.errors import CustomerCreditExceeded
from domains.customers.repository import CustomersRepository
from domains.customers.schema import (
    DEFAULT_CUSTOMER_CREDIT_LIMIT,
    CreateCustomerRequest,
    CreditCheckResult,
    CustomerCreditBalance,
    CustomerProfile,
    UpdateCustomerRequest,
)
from infra.core.errors import AppError, ErrorCode


def _normalize_company_name(company_name: str | None) -> str:
    normalized = str(company_name or "").strip()
    if not normalized:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="公司名称不能为空。",
            status_code=400,
        )
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


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
        normalized_payload = payload.model_copy(
            update={
                "company_name": _normalize_company_name(payload.company_name),
                "contact_name": _normalize_optional_text(payload.contact_name),
                "phone": _normalize_optional_text(payload.phone),
                "email": _normalize_optional_text(payload.email),
                "address": _normalize_optional_text(payload.address),
            }
        )
        row = await self.repository.create_customer(session, normalized_payload)
        return CustomerProfile.model_validate(row)

    async def create_workspace_customer(
        self,
        session: AsyncSession,
        *,
        company_name: str,
        contact_name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
    ) -> CustomerProfile:
        return await self.create_customer(
            session,
            CreateCustomerRequest(
                company_name=company_name,
                contact_name=contact_name,
                phone=phone,
                email=email,
                address=address,
                credit_limit=DEFAULT_CUSTOMER_CREDIT_LIMIT,
            ),
        )

    async def update_customer(
        self,
        session: AsyncSession,
        customer_id: str,
        payload: UpdateCustomerRequest,
    ) -> CustomerProfile:
        update_data: dict = {}
        if "company_name" in payload.model_fields_set:
            update_data["company_name"] = _normalize_company_name(payload.company_name)
        if "contact_name" in payload.model_fields_set:
            update_data["contact_name"] = _normalize_optional_text(payload.contact_name)
        if "phone" in payload.model_fields_set:
            update_data["phone"] = _normalize_optional_text(payload.phone)
        if "email" in payload.model_fields_set:
            update_data["email"] = _normalize_optional_text(payload.email)
        if "address" in payload.model_fields_set:
            update_data["address"] = _normalize_optional_text(payload.address)
        if "credit_limit" in payload.model_fields_set and payload.credit_limit is not None:
            if payload.credit_limit < 0:
                raise AppError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="授信额度不能为负数。",
                    status_code=400,
                )
            update_data["credit_limit"] = payload.credit_limit

        normalized_payload = payload.model_copy(update=update_data)
        row = await self.repository.update_customer(session, customer_id, normalized_payload)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="客户不存在。",
                status_code=404,
                details={"customer_id": customer_id},
            )
        return CustomerProfile.model_validate(row)

    async def get_customer_profile(
        self, session: AsyncSession, customer_id: str
    ) -> CustomerProfile:
        row = await self.repository.get_customer(session, customer_id)
        if row is None:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Customer not found.",
                status_code=404,
                details={"customer_id": customer_id},
            )
        return CustomerProfile.model_validate(row)

    async def get_credit_balance(
        self, session: AsyncSession, customer_id: str
    ) -> CustomerCreditBalance:
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
