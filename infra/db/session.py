from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from infra.core.config import get_settings
from infra.core.hooks import execute_after_commit_hooks, pop_after_commit_hooks
from infra.db.base import Base


@lru_cache(maxsize=1)
def build_engine() -> AsyncEngine:
    settings = get_settings()

    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }

    if settings.database.use_null_pool:
        return create_async_engine(
            settings.database.url,
            echo=settings.database.echo,
            poolclass=NullPool,
            connect_args=connect_args,
        )

    return create_async_engine(
        settings.database.url,
        echo=settings.database.echo,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def build_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=build_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = build_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
            await execute_after_commit_hooks(session)
        except Exception:
            pop_after_commit_hooks(session)
            await session.rollback()
            raise


async def init_models() -> None:
    from infra.db import models as _models  # noqa: F401

    engine = build_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
