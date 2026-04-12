from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from domains.customers.schema import DEFAULT_CUSTOMER_CREDIT_LIMIT, UpdateCustomerRequest
from domains.customers.service import CustomersService
from infra.core.errors import AppError
from infra.db.models.customers import CustomerModel


def _build_customer(
    *,
    company_name: str,
    contact_name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    credit_limit: Decimal = DEFAULT_CUSTOMER_CREDIT_LIMIT,
) -> CustomerModel:
    now = datetime.now(timezone.utc)
    return CustomerModel(
        id="cust-1",
        customer_code="CUST-TEST-0001",
        company_name=company_name,
        contact_name=contact_name,
        phone=phone,
        email=email,
        address=address,
        credit_limit=credit_limit,
        credit_used=Decimal("0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )


class _FakeCustomersRepository:
    def __init__(self) -> None:
        self.created_payload = None
        self.updated_payload = None

    async def create_customer(self, _session, payload):
        self.created_payload = payload
        return _build_customer(
            company_name=payload.company_name,
            contact_name=payload.contact_name,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            credit_limit=payload.credit_limit,
        )

    async def update_customer(self, _session, customer_id, payload):
        self.updated_payload = (customer_id, payload)
        return _build_customer(
            company_name=payload.company_name or "Updated Co",
            contact_name=payload.contact_name,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
        )


def test_create_workspace_customer_uses_default_credit_limit() -> None:
    repository = _FakeCustomersRepository()
    service = CustomersService(repository=repository)

    profile = asyncio.run(
        service.create_workspace_customer(
            None,
            company_name="  Demo Customer  ",
            contact_name="  Alice  ",
            phone=" 13800000000 ",
            email=" demo@example.com ",
            address=" Pickup desk ",
        )
    )

    assert repository.created_payload is not None
    assert repository.created_payload.company_name == "Demo Customer"
    assert repository.created_payload.contact_name == "Alice"
    assert repository.created_payload.phone == "13800000000"
    assert repository.created_payload.email == "demo@example.com"
    assert repository.created_payload.address == "Pickup desk"
    assert repository.created_payload.credit_limit == DEFAULT_CUSTOMER_CREDIT_LIMIT
    assert profile.company_name == "Demo Customer"


def test_update_customer_rejects_blank_company_name() -> None:
    repository = _FakeCustomersRepository()
    service = CustomersService(repository=repository)

    try:
        asyncio.run(
            service.update_customer(None, "cust-1", UpdateCustomerRequest(company_name="   "))
        )
    except AppError as exc:
        assert exc.status_code == 400
        assert exc.message == "公司名称不能为空。"
    else:
        raise AssertionError("Expected AppError for blank company name")

    assert repository.updated_payload is None
