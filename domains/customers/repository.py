from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.schema import CreateCustomerRequest
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
            select(CustomerModel)
            .order_by(CustomerModel.updated_at.desc())
            .limit(limit)
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
