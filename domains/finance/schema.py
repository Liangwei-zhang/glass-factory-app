from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReceivableView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    customer_id: str
    amount: Decimal
    paid_amount: Decimal
    status: str
    due_date: date
    created_at: datetime
    updated_at: datetime


class StatementView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: str
    order_id: str
    amount: Decimal
    paid_amount: Decimal
    status: str
    due_date: date
    created_at: datetime


class InvoiceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    invoice_no: str | None = None
    customer_id: str
    order_id: str
    amount: Decimal
    paid_amount: Decimal
    status: str
    due_date: date
    created_at: datetime
