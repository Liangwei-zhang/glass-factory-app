from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth.repository import AuthRepository
from domains.auth.schema import LoginRequest, LoginResponse, LoginUser
from infra.core.config import get_settings
from infra.core.errors import AppError, ErrorCode
from infra.security.auth import create_access_token
from infra.security.identity import (
    can_create_orders,
    resolve_canonical_role,
    resolve_home_path,
    resolve_shell_name,
    resolve_stage_label,
    resolve_user_scopes,
)
from infra.security.passwords import verify_password


class AuthService:
    def __init__(self, repository: AuthRepository | None = None) -> None:
        self.repository = repository or AuthRepository()

    async def login(self, session: AsyncSession, payload: LoginRequest) -> LoginResponse:
        principal = payload.principal
        if not principal:
            raise AppError(
                code=ErrorCode.BAD_REQUEST,
                message="username, email, phone, whatsappId, or wechatId is required.",
                status_code=400,
            )

        user = await self.repository.get_by_principal(session, principal)

        if user is None or not verify_password(payload.password, user.password_hash):
            raise AppError(
                code=ErrorCode.UNAUTHORIZED,
                message="Invalid username or password.",
                status_code=401,
            )

        if not user.is_active:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="User account is disabled.",
                status_code=403,
            )

        settings = get_settings()
        resolved_scopes = resolve_user_scopes(
            user.role,
            scopes=user.scopes or [],
            stage=user.stage,
        )
        canonical_role = resolve_canonical_role(user.role)

        access_token = create_access_token(
            subject=user.id,
            role=canonical_role,
            scopes=resolved_scopes,
            stage=user.stage,
            customer_id=user.customer_id,
        )

        return LoginResponse(
            access_token=access_token,
            token=access_token,
            expires_in=settings.security.access_token_minutes * 60,
            user=LoginUser(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                role=canonical_role,
                scopes=resolved_scopes,
                stage=user.stage,
                customerId=user.customer_id,
                stageLabel=resolve_stage_label(user.stage),
                canonicalRole=canonical_role,
                homePath=resolve_home_path(user.role),
                shell=resolve_shell_name(user.role),
                canCreateOrders=can_create_orders(user.role),
            ),
        )
