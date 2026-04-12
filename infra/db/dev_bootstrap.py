from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from infra.db.models.customers import CustomerModel
from infra.db.models.users import UserModel
from infra.db.session import build_session_factory
from infra.security.passwords import hash_password

DEMO_CUSTOMER = {
    "customer_code": "CUST-DEMO-APP",
    "company_name": "Demo Customer Portal",
    "contact_name": "Demo Customer",
    "phone": "13800000000",
    "email": "customer@glass.local",
    "address": "Demo Pickup Desk",
    "credit_limit": Decimal("100000.00"),
}

DEMO_USERS = (
    {
        "username": "office",
        "display_name": "Operations Desk",
        "email": "office@glass.local",
        "password": "office123",
        "role": "operator",
        "stage": None,
    },
    {
        "username": "cutting",
        "display_name": "Cutting Operator",
        "email": "cutting@glass.local",
        "password": "worker123",
        "role": "operator",
        "stage": "cutting",
    },
    {
        "username": "edging",
        "display_name": "Edging Operator",
        "email": "edging@glass.local",
        "password": "worker123",
        "role": "operator",
        "stage": "edging",
    },
    {
        "username": "tempering",
        "display_name": "Tempering Operator",
        "email": "tempering@glass.local",
        "password": "worker123",
        "role": "operator",
        "stage": "tempering",
    },
    {
        "username": "finishing",
        "display_name": "Finishing Operator",
        "email": "finishing@glass.local",
        "password": "worker123",
        "role": "operator",
        "stage": "finishing",
    },
    {
        "username": "supervisor",
        "display_name": "Production Manager",
        "email": "supervisor@glass.local",
        "password": "supervisor123",
        "role": "manager",
        "stage": None,
    },
    {
        "username": "customer-demo",
        "display_name": "Demo Customer",
        "email": "customer@glass.local",
        "password": "customer123",
        "role": "customer",
        "stage": None,
    },
    {
        "username": "customer-viewer-demo",
        "display_name": "Demo Customer Viewer",
        "email": "customer-viewer@glass.local",
        "password": "viewer123",
        "role": "customer_viewer",
        "stage": None,
    },
)


async def ensure_dev_demo_users() -> int:
    session_factory = build_session_factory()

    async with session_factory() as session:
        customer = None
        customer_result = await session.execute(
            select(CustomerModel).where(
                CustomerModel.customer_code == DEMO_CUSTOMER["customer_code"]
            )
        )
        customer = customer_result.scalar_one_or_none()
        if customer is None:
            customer = CustomerModel(
                **DEMO_CUSTOMER, credit_used=Decimal("0.00"), price_level="standard", is_active=True
            )
            session.add(customer)
            await session.flush()

        changed = 0
        for user in DEMO_USERS:
            existing_result = await session.execute(
                select(UserModel).where(
                    or_(UserModel.username == user["username"], UserModel.email == user["email"])
                )
            )
            existing = existing_result.scalar_one_or_none()
            desired_customer_id = (
                customer.id if user["role"] in {"customer", "customer_viewer"} else None
            )
            desired_password_hash = hash_password(user["password"])
            if existing is not None:
                updated = False
                desired_fields = {
                    "email": user["email"],
                    "password_hash": desired_password_hash,
                    "display_name": user["display_name"],
                    "role": user["role"],
                    "stage": user["stage"],
                    "customer_id": desired_customer_id,
                    "scopes": [],
                    "is_active": True,
                }
                for field_name, desired_value in desired_fields.items():
                    if getattr(existing, field_name) != desired_value:
                        setattr(existing, field_name, desired_value)
                        updated = True
                if updated:
                    changed += 1
                continue

            session.add(
                UserModel(
                    username=user["username"],
                    email=user["email"],
                    customer_id=desired_customer_id,
                    password_hash=desired_password_hash,
                    display_name=user["display_name"],
                    role=user["role"],
                    stage=user["stage"],
                    scopes=[],
                    is_active=True,
                )
            )
            changed += 1

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 0

    return changed
