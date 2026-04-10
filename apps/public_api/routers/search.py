from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.customers import CustomerModel
from infra.db.models.orders import OrderModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def global_search(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    _ = user

    keyword = q.strip()
    if not keyword:
        return {"keyword": keyword, "orders": [], "customers": []}

    pattern = f"%{keyword}%"
    order_rows = await session.execute(
        select(OrderModel)
        .where(
            or_(
                OrderModel.order_no.ilike(pattern),
                OrderModel.status.ilike(pattern),
                OrderModel.remark.ilike(pattern),
            )
        )
        .order_by(OrderModel.created_at.desc())
        .limit(limit)
    )
    customer_rows = await session.execute(
        select(CustomerModel)
        .where(
            or_(
                CustomerModel.company_name.ilike(pattern),
                CustomerModel.contact_name.ilike(pattern),
                CustomerModel.phone.ilike(pattern),
                CustomerModel.email.ilike(pattern),
            )
        )
        .order_by(CustomerModel.updated_at.desc())
        .limit(limit)
    )

    orders = [
        {
            "id": row.id,
            "order_no": row.order_no,
            "status": row.status,
            "customer_id": row.customer_id,
            "created_at": row.created_at,
        }
        for row in order_rows.scalars().all()
    ]
    customers = [
        {
            "id": row.id,
            "customer_code": row.customer_code,
            "company_name": row.company_name,
            "contact_name": row.contact_name,
            "phone": row.phone,
            "email": row.email,
        }
        for row in customer_rows.scalars().all()
    ]

    return {"keyword": keyword, "orders": orders, "customers": customers}
