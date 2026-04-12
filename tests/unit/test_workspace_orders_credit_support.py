from __future__ import annotations

from decimal import Decimal

from domains.workspace.orders_support import (
    WORKSPACE_DEFAULT_CREDIT_LIMIT,
    ensure_workspace_customer_credit_limit,
)
from infra.db.models.customers import CustomerModel


def _build_customer(credit_limit: Decimal) -> CustomerModel:
    return CustomerModel(
        customer_code="CUST-TEST-0001",
        company_name="Compatibility Customer",
        credit_limit=credit_limit,
        credit_used=Decimal("0"),
        is_active=True,
    )


def test_ensure_workspace_customer_credit_limit_backfills_zero_credit() -> None:
    customer = _build_customer(Decimal("0"))

    changed = ensure_workspace_customer_credit_limit(customer)

    assert changed is True
    assert customer.credit_limit == WORKSPACE_DEFAULT_CREDIT_LIMIT


def test_ensure_workspace_customer_credit_limit_preserves_existing_positive_credit() -> None:
    customer = _build_customer(Decimal("2500.00"))

    changed = ensure_workspace_customer_credit_limit(customer)

    assert changed is False
    assert customer.credit_limit == Decimal("2500.00")