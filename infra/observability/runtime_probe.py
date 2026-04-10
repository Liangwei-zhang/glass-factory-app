from __future__ import annotations

import asyncio

from sqlalchemy import text

from infra.cache.redis_client import get_redis
from infra.core.config import get_settings
from infra.db.session import build_engine


async def check_database() -> bool:
    engine = build_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_redis() -> bool:
    try:
        client = await get_redis()
        pong = await client.ping()
        return bool(pong)
    except Exception:
        return False


def _parse_kafka_bootstrap_servers(raw: str) -> list[tuple[str, int]]:
    endpoints: list[tuple[str, int]] = []
    for value in raw.split(","):
        item = value.strip()
        if not item:
            continue
        if "://" in item:
            item = item.split("://", maxsplit=1)[1]

        host, separator, port_text = item.rpartition(":")
        if not separator:
            host = item
            port = 9092
        else:
            try:
                port = int(port_text)
            except ValueError:
                port = 9092
        if host:
            endpoints.append((host, port))
    return endpoints


async def _check_tcp_endpoint(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def check_kafka() -> bool:
    settings = get_settings()
    endpoints = _parse_kafka_bootstrap_servers(settings.events.kafka_bootstrap_servers)
    if not endpoints:
        return False

    for host, port in endpoints:
        if await _check_tcp_endpoint(host, port):
            return True
    return False


async def run_runtime_probe() -> dict:
    db_ok = await check_database()
    redis_ok = await check_redis()
    kafka_ok = await check_kafka()

    status = "ok" if db_ok and redis_ok and kafka_ok else "degraded"
    return {
        "status": status,
        "checks": {
            "database": db_ok,
            "redis": redis_ok,
            "kafka": kafka_ok,
        },
    }
