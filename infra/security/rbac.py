from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from infra.core.errors import AppError, ErrorCode
from infra.security.auth import AuthUser, get_current_user


def require_scopes(required_scopes: list[str]) -> Callable:
    async def _dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        missing = [scope for scope in required_scopes if scope not in user.scopes]
        if missing:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Missing required permissions.",
                status_code=403,
                details={"missing_scopes": missing},
            )
        return user

    return _dependency


def require_roles(roles: list[str]) -> Callable:
    allowed = {role.lower() for role in roles}

    async def _dependency(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.role.lower() not in allowed:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Role is not allowed for this endpoint.",
                status_code=403,
                details={"required_roles": sorted(allowed), "actual_role": user.role},
            )
        return user

    return _dependency
