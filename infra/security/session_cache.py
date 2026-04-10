from __future__ import annotations

import hashlib

from infra.cache.redis_client import get_redis


def _session_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"session:{digest}"


async def set_session(token: str, user_id: str, ttl_seconds: int = 1800) -> None:
    redis = await get_redis()
    await redis.set(_session_key(token), user_id, ex=ttl_seconds)


async def get_session_user_id(token: str) -> str | None:
    redis = await get_redis()
    return await redis.get(_session_key(token))


async def clear_session(token: str) -> None:
    redis = await get_redis()
    await redis.delete(_session_key(token))
