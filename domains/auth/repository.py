from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.db.models.users import UserModel


class AuthRepository:
    async def get_by_username(self, session: AsyncSession, username: str) -> UserModel | None:
        result = await session.execute(select(UserModel).where(UserModel.username == username))
        return result.scalar_one_or_none()

    async def get_by_principal(self, session: AsyncSession, principal: str) -> UserModel | None:
        result = await session.execute(
            select(UserModel).where(
                or_(
                    UserModel.username == principal,
                    UserModel.email == principal,
                    UserModel.phone == principal,
                    UserModel.whatsapp_id == principal,
                    UserModel.wechat_id == principal,
                )
            )
        )
        return result.scalar_one_or_none()
