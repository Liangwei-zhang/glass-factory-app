import hashlib
import json
import secrets

from fastapi import APIRouter, Body, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth.schema import LoginRequest, LoginResponse
from domains.auth.service import AuthService
from infra.core.config import get_settings
from infra.cache.redis_client import get_redis
from infra.core.errors import AppError, ErrorCode
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, create_access_token, get_current_user
from infra.security.idempotency import enforce_idempotency_key
from infra.security.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])
service = AuthService()
settings = get_settings()
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


def _refresh_session_id(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _refresh_session_key(refresh_token: str) -> str:
    return f"session:{_refresh_session_id(refresh_token)}"


class LogoutResponse(BaseModel):
    success: bool = True


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, alias="refreshToken")


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")


class RefreshTokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int


class SendCodeRequest(BaseModel):
    target: str
    channel: str = "email"


class SendCodeResponse(BaseModel):
    accepted: bool
    channel: str
    target: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
@limiter.limit("30/minute")
async def login(
    request: Request,
    payload: LoginRequest = Body(...),
    session: AsyncSession = Depends(get_db_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LoginResponse:
    _ = request
    await enforce_idempotency_key("auth:login", idempotency_key)
    login_result = await service.login(session, payload)

    refresh_token = secrets.token_urlsafe(48)
    session_id = _refresh_session_id(refresh_token)
    refresh_session_payload = {
        "user_id": login_result.user.id,
        "role": login_result.user.role,
        "scopes": login_result.user.scopes,
        "stage": login_result.user.stage,
    }

    redis = await get_redis()
    await redis.set(
        _refresh_session_key(refresh_token),
        json.dumps(refresh_session_payload),
        ex=REFRESH_TOKEN_TTL_SECONDS,
    )

    access_token = create_access_token(
        subject=login_result.user.id,
        role=login_result.user.role,
        scopes=login_result.user.scopes,
        stage=login_result.user.stage,
        session_id=session_id,
    )

    return login_result.model_copy(
        update={
            "access_token": access_token,
            "token": access_token,
            "refresh_token": refresh_token,
        }
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: LogoutRequest = Body(default_factory=LogoutRequest),
    user: AuthUser = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LogoutResponse:
    _ = user
    await enforce_idempotency_key("auth:logout", idempotency_key)

    if payload.refresh_token:
        redis = await get_redis()
        await redis.delete(_refresh_session_key(payload.refresh_token))

    return LogoutResponse()


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RefreshTokenResponse:
    await enforce_idempotency_key("auth:refresh", idempotency_key)
    redis = await get_redis()
    session_key = _refresh_session_key(payload.refresh_token)
    raw_session = await redis.get(session_key)

    if not raw_session:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Refresh token is invalid or expired.",
            status_code=401,
        )

    try:
        refresh_session = json.loads(raw_session)
    except json.JSONDecodeError as exc:
        raise AppError(
            code=ErrorCode.INTERNAL_ERROR,
            message="Refresh token session payload is corrupted.",
            status_code=500,
        ) from exc

    user_id = str(refresh_session.get("user_id") or "").strip()
    role = str(refresh_session.get("role") or "").strip()
    scopes = list(refresh_session.get("scopes") or [])
    stage = refresh_session.get("stage")

    if not user_id or not role:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Refresh token session is incomplete.",
            status_code=401,
        )

    session_id = _refresh_session_id(payload.refresh_token)
    access_token = create_access_token(
        subject=user_id,
        role=role,
        scopes=scopes,
        stage=stage,
        session_id=session_id,
    )

    await redis.expire(session_key, REFRESH_TOKEN_TTL_SECONDS)

    return RefreshTokenResponse(
        access_token=access_token,
        refresh_token=payload.refresh_token,
        expires_in=settings.security.access_token_minutes * 60,
    )


@router.post("/send-code", response_model=SendCodeResponse)
@limiter.limit("20/minute")
async def send_code(
    request: Request,
    payload: SendCodeRequest = Body(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SendCodeResponse:
    _ = request
    await enforce_idempotency_key("auth:send-code", idempotency_key)
    code = "".join(str(secrets.randbelow(10)) for _ in range(6))
    redis = await get_redis()
    key = f"otp:{payload.channel}:{payload.target.strip().lower()}"
    await redis.set(key, code, ex=300)
    return SendCodeResponse(
        accepted=True,
        channel=payload.channel,
        target=payload.target,
        expires_in=300,
    )
