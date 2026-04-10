from __future__ import annotations

import json

from infra.cache.redis_client import get_redis


def _key(customer_id: str) -> str:
    return f"cache:customer:{customer_id}"


async def get_customer_cache(customer_id: str) -> dict | None:
    client = await get_redis()
    payload = await client.get(_key(customer_id))
    if payload is None:
        return None
    return json.loads(payload)


async def set_customer_cache(customer_id: str, data: dict, ttl_seconds: int = 60) -> None:
    client = await get_redis()
    await client.set(_key(customer_id), json.dumps(data), ex=ttl_seconds)


async def invalidate_customer_cache(customer_id: str) -> None:
    client = await get_redis()
    await client.delete(_key(customer_id))
