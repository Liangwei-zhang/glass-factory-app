from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from domains.customers.schema import CreateCustomerRequest, CustomerCreditBalance, CustomerProfile
from domains.customers.service import CustomersService
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user
from infra.security.idempotency import enforce_idempotency_key

router = APIRouter(prefix="/customers", tags=["customers"])
service = CustomersService()


@router.get("", response_model=list[CustomerProfile])
async def list_customers(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> list[CustomerProfile]:
    _ = user
    return await service.list_customers(session, limit=limit)


@router.post("", response_model=CustomerProfile, status_code=201)
async def create_customer(
    payload: CreateCustomerRequest,
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CustomerProfile:
    _ = user
    await enforce_idempotency_key("customers:create", idempotency_key)
    return await service.create_customer(session, payload)


@router.get("/profile", response_model=CustomerProfile)
async def get_customer_profile(
    customer_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> CustomerProfile:
    default_customer_id = user.customer_id if user.role.lower() in {"customer", "customer_viewer"} else user.user_id
    target_customer_id = customer_id or default_customer_id
    return await service.get_customer_profile(session, customer_id=target_customer_id)


@router.get("/credit", response_model=CustomerCreditBalance)
async def get_customer_credit(
    customer_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> CustomerCreditBalance:
    default_customer_id = user.customer_id if user.role.lower() in {"customer", "customer_viewer"} else user.user_id
    target_customer_id = customer_id or default_customer_id
    return await service.get_credit_balance(session, customer_id=target_customer_id)
