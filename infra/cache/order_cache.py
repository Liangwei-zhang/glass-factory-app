from __future__ import annotations

import json

from infra.cache.redis_client import get_redis


def _key(order_id: str) -> str:
    return f"cache:order:{order_id}"


async def get_order_cache(order_id: str) -> dict | None:
    client = await get_redis()
    payload = await client.get(_key(order_id))
    if payload is None:
        return None
    return json.loads(payload)


async def set_order_cache(order_id: str, data: dict, ttl_seconds: int = 30) -> None:
    client = await get_redis()
    await client.set(_key(order_id), json.dumps(data), ex=ttl_seconds)


async def invalidate_order_cache(order_id: str) -> None:
    client = await get_redis()
    await client.delete(_key(order_id))
