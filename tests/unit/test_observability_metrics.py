from __future__ import annotations

import asyncio

from infra.observability import metrics


async def _fake_collect_runtime_snapshot(_session) -> dict:
    return {
        "checks": {"database": True, "redis": True, "kafka": True},
        "redis_memory_used_bytes": 2048.0,
        "redis_connected_clients": 7.0,
        "redis_memory_utilization_ratio": 0.5,
        "clickhouse_up": True,
        "pgbouncer_waiting_clients": 3.0,
        "kafka_consumer_lag": 42.0,
        "outbox_records": {"pending": 1.0, "published": 2.0, "failed": 0.0, "dead_letter": 0.0},
    }


def test_metrics_response_includes_runtime_gauges(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "collect_runtime_snapshot", _fake_collect_runtime_snapshot)

    async def _run():
        return await metrics.metrics_response(session=None)  # type: ignore[arg-type]

    response = asyncio.run(_run())
    payload = response.body.decode("utf-8")

    assert "glass_factory_pgbouncer_waiting_clients" in payload
    assert "glass_factory_kafka_consumer_lag" in payload
    assert "glass_factory_redis_memory_utilization_ratio" in payload
