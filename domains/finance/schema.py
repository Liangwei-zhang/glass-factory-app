from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CreateReceivableRequest(BaseModel):
    order_id: str
    due_date: date
    amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    invoice_no: str | None = Field(default=None, max_length=30)


class RecordPaymentRequest(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"))


class RecordRefundRequest(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"))


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
