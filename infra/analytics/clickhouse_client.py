from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

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

    async def ping(self) -> bool:
        try:
            result = await self.execute("SELECT 1")
        except Exception:
            return False
        return result.strip() == "1"

    async def query_json_rows(self, sql: str) -> list[dict[str, Any]]:
        payload = await self.execute(f"{sql.rstrip()}\nFORMAT JSON")
        parsed = json.loads(payload)
        return list(parsed.get("data") or [])

    async def insert_json_rows(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        sql = "INSERT INTO {table_name} FORMAT JSONEachRow\n{payload}".format(
            table_name=table_name,
            payload="\n".join(json.dumps(row, ensure_ascii=True, default=str) for row in rows),
        )
        await self.execute(sql)
