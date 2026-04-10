from __future__ import annotations

import hashlib
import hmac

from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth.repository import AuthRepository
from domains.auth.schema import LoginRequest, LoginResponse, LoginUser
from infra.core.config import get_settings
from infra.core.errors import AppError, ErrorCode
from infra.security.auth import create_access_token

STAGE_LABELS: dict[str, str] = {
    "cutting": "切玻璃工人",
    "edging": "开切口工人",
    "tempering": "钢化工人",
    "finishing": "完成钢化处工人",
}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _verify_password(raw_password: str, stored_password_hash: str) -> bool:
    candidate_hash = _hash_password(raw_password)
    return hmac.compare_digest(candidate_hash, stored_password_hash) or hmac.compare_digest(
        raw_password,
        stored_password_hash,
    )


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

        if user is None or not _verify_password(payload.password, user.password_hash):
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
        access_token = create_access_token(
            subject=user.id,
            role=user.role,
            scopes=user.scopes or [],
            stage=user.stage,
        )

        return LoginResponse(
            access_token=access_token,
            token=access_token,
            expires_in=settings.security.access_token_minutes * 60,
            user=LoginUser(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                role=user.role,
                scopes=user.scopes or [],
                stage=user.stage,
                stageLabel=STAGE_LABELS.get(user.stage or "") if user.stage else None,
            ),
        )
