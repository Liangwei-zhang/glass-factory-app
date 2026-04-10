from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from infra.cache.redis_client import get_redis
from infra.core.config import get_settings
from infra.core.errors import AppError, ErrorCode


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


class AuthUser(BaseModel):
    user_id: str = Field(alias="sub")
    role: str = "operator"
    scopes: list[str] = Field(default_factory=list)
    stage: str | None = None
    session_id: str | None = Field(default=None, alias="sid")


def create_access_token(
    subject: str,
    role: str,
    scopes: list[str] | None = None,
    stage: str | None = None,
    session_id: str | None = None,
) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.security.access_token_minutes
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "scopes": scopes or [],
        "exp": expires_at,
    }
    if stage:
        payload["stage"] = stage
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, settings.security.jwt_secret, algorithm=settings.security.jwt_algorithm)


def decode_access_token(token: str) -> AuthUser:
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.security.jwt_secret,
            algorithms=[settings.security.jwt_algorithm],
        )
        return AuthUser(**payload)
    except JWTError as exc:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid or expired token.",
            status_code=401,
        ) from exc


async def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthUser:
    user = decode_access_token(token)

    if not user.session_id:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Session claim is missing from access token.",
            status_code=401,
        )

    redis = await get_redis()
    raw_session = await redis.get(f"session:{user.session_id}")
    if not raw_session:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Session is invalid or expired.",
            status_code=401,
        )

    try:
        session_payload = json.loads(raw_session)
    except json.JSONDecodeError as exc:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Session payload is corrupted.",
            status_code=401,
        ) from exc

    session_user_id = str(session_payload.get("user_id") or "").strip()
    if session_user_id != user.user_id:
        raise AppError(
            code=ErrorCode.UNAUTHORIZED,
            message="Session user does not match access token.",
            status_code=401,
        )

    return user
