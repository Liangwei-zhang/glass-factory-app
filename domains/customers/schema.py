from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

DEFAULT_CUSTOMER_CREDIT_LIMIT = Decimal("1000000.00")


class CustomerProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_code: str
    company_name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    credit_limit: Decimal
    credit_used: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreateCustomerRequest(BaseModel):
    company_name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    credit_limit: Decimal = Decimal("0")


class UpdateCustomerRequest(BaseModel):
    company_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    credit_limit: Decimal | None = None


class CreditCheckResult(BaseModel):
    allowed: bool
    credit_limit: Decimal
    credit_used: Decimal
    available_credit: Decimal


class CustomerCreditBalance(BaseModel):
    customer_id: str
    credit_limit: Decimal
    credit_used: Decimal
    available_credit: Decimal
