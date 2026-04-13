from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.schema import CreateCustomerRequest, UpdateCustomerRequest
from infra.db.models.customers import CustomerModel


class CustomersRepository:
    async def get_customer(self, session: AsyncSession, customer_id: str) -> CustomerModel | None:
        result = await session.execute(select(CustomerModel).where(CustomerModel.id == customer_id))
        return result.scalar_one_or_none()

    async def list_customers(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> list[CustomerModel]:
        result = await session.execute(
            select(CustomerModel).order_by(CustomerModel.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def create_customer(
        self,
        session: AsyncSession,
        payload: CreateCustomerRequest,
    ) -> CustomerModel:
        now = datetime.now(timezone.utc)
        customer = CustomerModel(
            id=str(uuid4()),
            customer_code=f"CUST-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
            company_name=payload.company_name,
            contact_name=payload.contact_name,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            credit_limit=payload.credit_limit,
            credit_used=0,
            is_active=True,
        )
        session.add(customer)
        await session.flush()
        await session.refresh(customer)
        return customer

    async def update_customer(
        self,
        session: AsyncSession,
        customer_id: str,
        payload: UpdateCustomerRequest,
    ) -> CustomerModel | None:
        customer = await self.get_customer(session, customer_id)
        if customer is None:
            return None

        provided_fields = payload.model_fields_set
        if "company_name" in provided_fields:
            customer.company_name = payload.company_name or customer.company_name
        if "contact_name" in provided_fields:
            customer.contact_name = payload.contact_name
        if "phone" in provided_fields:
            customer.phone = payload.phone
        if "email" in provided_fields:
            customer.email = payload.email
        if "address" in provided_fields:
            customer.address = payload.address
        if "credit_limit" in provided_fields and payload.credit_limit is not None:
            customer.credit_limit = payload.credit_limit

        await session.flush()
        await session.refresh(customer)
        return customer
