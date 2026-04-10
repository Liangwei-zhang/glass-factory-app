from __future__ import annotations

from datetime import datetime, timezone

from infra.cache.redis_client import get_redis


class OrderIdGenerator:
    def __init__(self, machine_id: int = 1) -> None:
        self.machine_id = machine_id

    async def generate(self, prefix: str = "GF") -> str:
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        redis_key = f"id_gen:{prefix}:{date_str}:{self.machine_id}"

        client = await get_redis()
        sequence = await client.incr(redis_key)

        if sequence == 1:
            await client.expire(redis_key, 172800)

        return f"{prefix}{date_str}-{self.machine_id:02d}-{sequence:06d}"
