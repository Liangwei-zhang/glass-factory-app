from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from infra.analytics.clickhouse_client import ClickHouseClient
from infra.cache.redis_client import get_redis
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
CLICKHOUSE_UP = Gauge(
    "glass_factory_clickhouse_up",
    "Whether ClickHouse is currently reachable.",
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


async def _update_runtime_metrics(session: AsyncSession) -> None:
    runtime_probe = await run_runtime_probe()
    checks = runtime_probe.get("checks", {})
    for component in ["database", "redis", "kafka"]:
        RUNTIME_COMPONENT_UP.labels(component=component).set(
            _status_to_float(checks.get(component))
        )

    redis_client = await get_redis()
    try:
        redis_memory_info = await redis_client.info(section="memory")
        REDIS_MEMORY_USED_BYTES.set(float(redis_memory_info.get("used_memory", 0) or 0))
    except Exception:
        REDIS_MEMORY_USED_BYTES.set(0)

    try:
        redis_clients_info = await redis_client.info(section="clients")
        REDIS_CONNECTED_CLIENTS.set(
            float(redis_clients_info.get("connected_clients", 0) or 0)
        )
    except Exception:
        REDIS_CONNECTED_CLIENTS.set(0)

    try:
        clickhouse_up = await ClickHouseClient().ping()
    except Exception:
        clickhouse_up = False
    CLICKHOUSE_UP.set(1.0 if clickhouse_up else 0.0)

    status_rows = await session.execute(
        select(EventOutboxModel.status, func.count(EventOutboxModel.id))
        .group_by(EventOutboxModel.status)
        .order_by(EventOutboxModel.status.asc())
    )
    counts_by_status = {str(status): int(count) for status, count in status_rows.all()}
    for status in ["pending", "published", "failed", "dead_letter"]:
        OUTBOX_RECORDS.labels(status=status).set(float(counts_by_status.get(status, 0)))


async def metrics_response(session: AsyncSession) -> Response:
    await _update_runtime_metrics(session)
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
