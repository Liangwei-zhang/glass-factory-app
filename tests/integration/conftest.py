from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from infra.cache import inventory_reservation, redis_client
from infra.core import id_generator
from infra.db import models as _models  # noqa: F401
from infra.db.base import Base

INTEGRATION_DATABASE_URL_ENV = "INTEGRATION_DATABASE_URL"
INTEGRATION_REDIS_URL_ENV = "INTEGRATION_REDIS_URL"


@dataclass(slots=True, frozen=True)
class RealInfraConfig:
    database_url: str
    redis_url: str


def _load_real_infra_config() -> RealInfraConfig:
    database_url = os.getenv(INTEGRATION_DATABASE_URL_ENV, "").strip()
    redis_url = os.getenv(INTEGRATION_REDIS_URL_ENV, "").strip()
    if not database_url or not redis_url:
        pytest.skip(
            "real infra integration tests require INTEGRATION_DATABASE_URL and "
            "INTEGRATION_REDIS_URL pointing to disposable test-only infra",
        )
    return RealInfraConfig(database_url=database_url, redis_url=redis_url)


@pytest.fixture
def real_infra_config() -> RealInfraConfig:
    return _load_real_infra_config()


@pytest_asyncio.fixture
async def real_db_session_factory(
    real_infra_config: RealInfraConfig,
) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        real_infra_config.database_url,
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest_asyncio.fixture
async def real_redis_client(real_infra_config: RealInfraConfig) -> Redis:
    client = Redis.from_url(real_infra_config.redis_url, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture
def patch_real_inventory_redis(monkeypatch: pytest.MonkeyPatch, real_redis_client: Redis) -> None:
    async def _get_redis() -> Redis:
        return real_redis_client

    monkeypatch.setattr(inventory_reservation, "get_redis", _get_redis)
    monkeypatch.setattr(redis_client, "get_redis", _get_redis)
    monkeypatch.setattr(id_generator, "get_redis", _get_redis)
