from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from infra.analytics.clickhouse_client import ClickHouseClient
from infra.db.models.events import EventOutboxModel
from infra.db.session import build_session_factory

FALLBACK_DIR = Path("data/analytics_fallback")
FALLBACK_FILE = FALLBACK_DIR / "event_outbox.jsonl"


def _to_jsonable_record(event: EventOutboxModel) -> dict:
    return {
        "event_id": event.id,
        "topic": event.topic,
        "event_key": event.event_key,
        "status": event.status,
        "payload": event.payload,
        "headers": event.headers,
        "attempt_count": event.attempt_count,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def _ensure_clickhouse_table(client: ClickHouseClient) -> None:
    await client.execute(
        """
        CREATE TABLE IF NOT EXISTS event_analytics (
            event_id String,
            topic String,
            event_key Nullable(String),
            status String,
            payload String,
            headers String,
            attempt_count UInt32,
            occurred_at DateTime,
            published_at Nullable(DateTime),
            created_at DateTime
        ) ENGINE = MergeTree
        ORDER BY (occurred_at, event_id)
        """
    )


async def _sink_to_clickhouse(client: ClickHouseClient, records: list[dict]) -> None:
    await _ensure_clickhouse_table(client)
    rows: list[str] = []
    for row in records:
        rows.append(
            json.dumps(
                {
                    "event_id": row["event_id"],
                    "topic": row["topic"],
                    "event_key": row["event_key"],
                    "status": row["status"],
                    "payload": json.dumps(row["payload"], ensure_ascii=True),
                    "headers": json.dumps(row["headers"], ensure_ascii=True),
                    "attempt_count": row["attempt_count"],
                    "occurred_at": row["occurred_at"] or datetime.now(timezone.utc).isoformat(),
                    "published_at": row["published_at"],
                    "created_at": row["created_at"] or datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=True,
            )
        )

    sql = "INSERT INTO event_analytics FORMAT JSONEachRow\n" + "\n".join(rows)
    await client.execute(sql)


def _sink_to_fallback_file(records: list[dict]) -> None:
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    with FALLBACK_FILE.open("a", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=True, default=str))
            handle.write("\n")


async def run_once(batch_size: int = 200) -> int:
    session_factory = build_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutboxModel)
            .where(EventOutboxModel.status == "published")
            .order_by(EventOutboxModel.published_at.asc(), EventOutboxModel.created_at.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())

        pending_rows = [row for row in rows if not bool((row.headers or {}).get("analytics_sunk"))]
        if not pending_rows:
            return 0

        records = [_to_jsonable_record(row) for row in pending_rows]
        sink_backend = "clickhouse"

        try:
            await _sink_to_clickhouse(ClickHouseClient(), records)
        except Exception as exc:
            sink_backend = "fallback_jsonl"
            logger.warning("analytics-sink clickhouse unavailable, fallback to file: {}", str(exc))
            _sink_to_fallback_file(records)

        sink_time = datetime.now(timezone.utc).isoformat()
        for row in pending_rows:
            headers = dict(row.headers or {})
            headers["analytics_sunk"] = True
            headers["analytics_sunk_at"] = sink_time
            headers["analytics_backend"] = sink_backend
            row.headers = headers

        await session.commit()

    logger.info(
        "analytics-sink worker exported events count={} backend={}",
        len(pending_rows),
        sink_backend,
    )
    return len(pending_rows)
