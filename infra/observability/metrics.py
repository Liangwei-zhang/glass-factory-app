from __future__ import annotations

from datetime import datetime, timezone
import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from infra.analytics.clickhouse_client import ClickHouseClient
from infra.cache.redis_client import get_redis
from infra.core.config import get_settings
from infra.db.models.events import EventOutboxModel
from infra.observability.runtime_probe import run_runtime_probe

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)
RUNTIME_COMPONENT_UP = Gauge(
    "glass_factory_runtime_component_up",
    "Whether a runtime dependency is currently reachable.",
    ["component"],
)
OUTBOX_RECORDS = Gauge(
    "glass_factory_event_outbox_records",
    "Number of outbox records grouped by status.",
    ["status"],
)
REDIS_MEMORY_USED_BYTES = Gauge(
    "glass_factory_redis_memory_used_bytes",
    "Redis memory currently in use, in bytes.",
)
REDIS_CONNECTED_CLIENTS = Gauge(
    "glass_factory_redis_connected_clients",
    "Redis connected client count.",
)
REDIS_MEMORY_UTILIZATION_RATIO = Gauge(
    "glass_factory_redis_memory_utilization_ratio",
    "Redis memory utilization ratio against configured maxmemory.",
)
CLICKHOUSE_UP = Gauge(
    "glass_factory_clickhouse_up",
    "Whether ClickHouse is currently reachable.",
)
PGBOUNCER_WAITING_CLIENTS = Gauge(
    "glass_factory_pgbouncer_waiting_clients",
    "PgBouncer clients currently waiting for a backend connection.",
)
KAFKA_CONSUMER_LAG = Gauge(
    "glass_factory_kafka_consumer_lag",
    "Aggregate Kafka consumer lag for the configured event topic.",
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started

        HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=str(response.status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(elapsed)

        return response


def _status_to_float(value) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, dict):
        return 1.0 if str(value.get("status") or "").lower() == "ok" else 0.0
    return 0.0


async def _fetch_pgbouncer_waiting_clients() -> float | None:
    try:
        import asyncpg
    except ModuleNotFoundError:
        return None

    settings = get_settings()
    try:
        database_url = make_url(settings.database.url)
    except Exception:
        return None

    if not database_url.host or not database_url.username:
        return None

    connection = None
    try:
        connection = await asyncpg.connect(
            host=database_url.host,
            port=int(database_url.port or 5432),
            user=database_url.username,
            password=database_url.password or None,
            database="pgbouncer",
            statement_cache_size=0,
            timeout=1,
        )
        rows = await connection.fetch("SHOW POOLS")
    except Exception:
        return None
    finally:
        if connection is not None:
            await connection.close()

    waiting_clients = 0
    for row in rows:
        payload = dict(row)
        waiting_clients += int(payload.get("cl_waiting") or payload.get("client_waiting") or 0)
    return float(waiting_clients)


async def _fetch_kafka_consumer_lag() -> float | None:
    try:
        from aiokafka import AIOKafkaConsumer
        from aiokafka.admin import AIOKafkaAdminClient
        from aiokafka.structs import TopicPartition
    except ModuleNotFoundError:
        return None

    settings = get_settings()
    admin_client = None
    consumer = None
    try:
        admin_client = AIOKafkaAdminClient(
            bootstrap_servers=settings.events.kafka_bootstrap_servers,
            client_id=f"{settings.app_name}-runtime-metrics",
        )
        await admin_client.start()
        groups = await admin_client.list_consumer_groups()
        group_ids = [
            str(group[0] if isinstance(group, tuple) else getattr(group, "group_id", group))
            for group in groups
        ]
        if not group_ids:
            return 0.0

        consumer = AIOKafkaConsumer(
            bootstrap_servers=settings.events.kafka_bootstrap_servers,
            enable_auto_commit=False,
        )
        await consumer.start()
        partitions = await consumer.partitions_for_topic(settings.events.kafka_topic)
        if not partitions:
            return 0.0

        topic_partitions = [
            TopicPartition(settings.events.kafka_topic, partition_id)
            for partition_id in sorted(partitions)
        ]
        end_offsets = await consumer.end_offsets(topic_partitions)

        total_lag = 0
        for group_id in group_ids:
            offsets = await admin_client.list_consumer_group_offsets(group_id)
            for topic_partition, offset_metadata in offsets.items():
                if topic_partition.topic != settings.events.kafka_topic:
                    continue
                committed_offset = int(getattr(offset_metadata, "offset", -1))
                if committed_offset < 0:
                    continue
                total_lag += max(int(end_offsets.get(topic_partition, committed_offset)) - committed_offset, 0)

        return float(total_lag)
    except Exception:
        return None
    finally:
        if consumer is not None:
            await consumer.stop()
        if admin_client is not None:
            await admin_client.close()


async def collect_runtime_snapshot(session: AsyncSession) -> dict:
    runtime_probe = await run_runtime_probe()
    checks = runtime_probe.get("checks", {})

    try:
        redis_client = await get_redis()
    except Exception:
        redis_client = None
    redis_memory_used_bytes = 0.0
    redis_connected_clients = 0.0
    redis_memory_utilization_ratio: float | None = None

    if redis_client is not None:
        try:
            redis_memory_info = await redis_client.info(section="memory")
            redis_memory_used_bytes = float(redis_memory_info.get("used_memory", 0) or 0)
            max_memory = float(redis_memory_info.get("maxmemory", 0) or 0)
            if max_memory > 0:
                redis_memory_utilization_ratio = redis_memory_used_bytes / max_memory
        except Exception:
            redis_memory_used_bytes = 0.0

        try:
            redis_clients_info = await redis_client.info(section="clients")
            redis_connected_clients = float(redis_clients_info.get("connected_clients", 0) or 0)
        except Exception:
            redis_connected_clients = 0.0

    try:
        clickhouse_up = await ClickHouseClient().ping()
    except Exception:
        clickhouse_up = False

    pgbouncer_waiting_clients = await _fetch_pgbouncer_waiting_clients()
    kafka_consumer_lag = await _fetch_kafka_consumer_lag()

    status_rows = await session.execute(
        select(EventOutboxModel.status, func.count(EventOutboxModel.id))
        .group_by(EventOutboxModel.status)
        .order_by(EventOutboxModel.status.asc())
    )
    counts_by_status = {str(status): int(count) for status, count in status_rows.all()}
    outbox_records = {
        status: float(counts_by_status.get(status, 0))
        for status in ["pending", "published", "failed", "dead_letter"]
    }

    return {
        "checks": checks,
        "redis_memory_used_bytes": redis_memory_used_bytes,
        "redis_connected_clients": redis_connected_clients,
        "redis_memory_utilization_ratio": redis_memory_utilization_ratio,
        "clickhouse_up": clickhouse_up,
        "pgbouncer_waiting_clients": pgbouncer_waiting_clients,
        "kafka_consumer_lag": kafka_consumer_lag,
        "outbox_records": outbox_records,
    }


def _apply_runtime_snapshot(snapshot: dict) -> None:
    checks = snapshot.get("checks", {})
    for component in ["database", "redis", "kafka"]:
        RUNTIME_COMPONENT_UP.labels(component=component).set(
            _status_to_float(checks.get(component))
        )

    REDIS_MEMORY_USED_BYTES.set(float(snapshot.get("redis_memory_used_bytes") or 0.0))
    REDIS_CONNECTED_CLIENTS.set(float(snapshot.get("redis_connected_clients") or 0.0))
    REDIS_MEMORY_UTILIZATION_RATIO.set(
        float(snapshot.get("redis_memory_utilization_ratio") or 0.0)
    )
    CLICKHOUSE_UP.set(1.0 if snapshot.get("clickhouse_up") else 0.0)
    PGBOUNCER_WAITING_CLIENTS.set(float(snapshot.get("pgbouncer_waiting_clients") or 0.0))
    KAFKA_CONSUMER_LAG.set(float(snapshot.get("kafka_consumer_lag") or 0.0))

    outbox_records = snapshot.get("outbox_records") or {}
    for status in ["pending", "published", "failed", "dead_letter"]:
        OUTBOX_RECORDS.labels(status=status).set(float(outbox_records.get(status, 0.0)))


def build_threshold_alerts(snapshot: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []

    pgbouncer_waiting_clients = snapshot.get("pgbouncer_waiting_clients")
    if pgbouncer_waiting_clients is not None and float(pgbouncer_waiting_clients) > 10:
        alerts.append(
            {
                "id": "runtime-threshold-pgbouncer-waiting",
                "type": "metric_threshold",
                "severity": "warning",
                "status": "warning",
                "metric": "glass_factory_pgbouncer_waiting_clients",
                "value": float(pgbouncer_waiting_clients),
                "threshold": 10.0,
                "message": "PgBouncer waiting clients exceeded the warning threshold.",
                "created_at": now,
            }
        )

    redis_memory_utilization_ratio = snapshot.get("redis_memory_utilization_ratio")
    if (
        redis_memory_utilization_ratio is not None
        and float(redis_memory_utilization_ratio) > 0.85
    ):
        alerts.append(
            {
                "id": "runtime-threshold-redis-memory",
                "type": "metric_threshold",
                "severity": "warning",
                "status": "warning",
                "metric": "glass_factory_redis_memory_utilization_ratio",
                "value": float(redis_memory_utilization_ratio),
                "threshold": 0.85,
                "message": "Redis memory utilization exceeded the warning threshold.",
                "created_at": now,
            }
        )

    kafka_consumer_lag = snapshot.get("kafka_consumer_lag")
    if kafka_consumer_lag is not None and float(kafka_consumer_lag) > 200:
        alerts.append(
            {
                "id": "runtime-threshold-kafka-lag",
                "type": "metric_threshold",
                "severity": "warning",
                "status": "warning",
                "metric": "glass_factory_kafka_consumer_lag",
                "value": float(kafka_consumer_lag),
                "threshold": 200.0,
                "message": "Kafka consumer lag exceeded the warning threshold.",
                "created_at": now,
            }
        )

    return alerts


async def metrics_response(session: AsyncSession) -> Response:
    snapshot = await collect_runtime_snapshot(session)
    _apply_runtime_snapshot(snapshot)
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
