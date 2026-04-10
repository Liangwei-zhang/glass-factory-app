from __future__ import annotations

from dataclasses import dataclass

import httpx

from infra.core.config import get_settings


@dataclass(slots=True)
class ClickHouseConfig:
    base_url: str = "http://localhost:8123"
    database: str = "default"

    @classmethod
    def from_settings(cls) -> "ClickHouseConfig":
        settings = get_settings()
        return cls(
            base_url=settings.analytics.clickhouse_base_url,
            database=settings.analytics.clickhouse_database,
        )


class ClickHouseClient:
    def __init__(self, config: ClickHouseConfig | None = None) -> None:
        self.config = config or ClickHouseConfig.from_settings()

    async def execute(self, sql: str) -> str:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                self.config.base_url,
                params={"database": self.config.database},
                content=sql.encode("utf-8"),
            )
            response.raise_for_status()
            return response.text
