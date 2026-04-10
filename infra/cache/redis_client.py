from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from infra.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis_pool() -> ConnectionPool:
    settings = get_settings()
    return ConnectionPool.from_url(
        settings.redis.url,
        max_connections=settings.redis.max_connections,
        decode_responses=True,
    )


async def get_redis() -> Redis:
    return Redis(connection_pool=get_redis_pool())
