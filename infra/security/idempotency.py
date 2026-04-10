from __future__ import annotations

import hashlib

from infra.cache.redis_client import get_redis
from infra.core.errors import AppError, ErrorCode


async def reserve_idempotency_key(namespace: str, raw_key: str, ttl_seconds: int = 86400) -> bool:
    normalized = raw_key.strip()
    if not normalized:
        return False

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    redis_key = f"idempotency:{namespace}:{digest}"

    redis = await get_redis()
    return bool(await redis.set(redis_key, "1", ex=ttl_seconds, nx=True))


async def enforce_idempotency_key(namespace: str, raw_key: str | None) -> str:
    normalized = (raw_key or "").strip()
    if not normalized:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Idempotency-Key header is required for write operations.",
            status_code=400,
            details={"namespace": namespace},
        )

    reserved = await reserve_idempotency_key(namespace, normalized)
    if not reserved:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Duplicate write request.",
            status_code=409,
            details={"namespace": namespace, "idempotency_key": normalized},
        )

    return normalized
