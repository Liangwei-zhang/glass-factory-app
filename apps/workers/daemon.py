from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from loguru import logger

from apps.workers.analytics_sink.main import run_once as run_analytics_sink
from apps.workers.cold_storage.main import run_once as run_cold_storage
from apps.workers.event_pipeline.main import run_once as run_event_pipeline
from apps.workers.inventory_sync.main import run_once as run_inventory_sync
from apps.workers.notification_dispatch.main import run_once as run_notification_dispatch
from apps.workers.order_timeout.main import run_once as run_order_timeout
from apps.workers.production_scheduler.main import run_once as run_production_scheduler
from apps.workers.retention.main import run_once as run_retention

RunOnceCallable = Callable[..., Awaitable[int]]


@dataclass(slots=True)
class WorkerSpec:
    run_once: RunOnceCallable
    interval_seconds: int
    default_kwargs: dict[str, Any] = field(default_factory=dict)


WORKERS: dict[str, WorkerSpec] = {
    "event-pipeline": WorkerSpec(
        run_once=run_event_pipeline,
        interval_seconds=1,
        default_kwargs={"batch_size": 200},
    ),
    "order-timeout": WorkerSpec(
        run_once=run_order_timeout,
        interval_seconds=30 * 60,
        default_kwargs={"batch_size": 200},
    ),
    "inventory-sync": WorkerSpec(
        run_once=run_inventory_sync,
        interval_seconds=5 * 60,
        default_kwargs={"batch_size": 500},
    ),
    "production-scheduler": WorkerSpec(
        run_once=run_production_scheduler,
        interval_seconds=15 * 60,
        default_kwargs={"batch_size": 200, "horizon_days": 14},
    ),
    "notification-dispatch": WorkerSpec(
        run_once=run_notification_dispatch,
        interval_seconds=30,
        default_kwargs={"batch_size": 200},
    ),
    "analytics-sink": WorkerSpec(
        run_once=run_analytics_sink,
        interval_seconds=2 * 60,
        default_kwargs={"batch_size": 200},
    ),
    "retention": WorkerSpec(
        run_once=run_retention,
        interval_seconds=24 * 60 * 60,
        default_kwargs={"event_batch_size": 500, "notification_batch_size": 500},
    ),
    "cold-storage": WorkerSpec(
        run_once=run_cold_storage,
        interval_seconds=24 * 60 * 60,
        default_kwargs={"batch_size": 200},
    ),
}


def _parse_kwargs(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for --kwargs: {exc.msg}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("--kwargs must be a JSON object")
    return parsed


async def _run_worker_loop(
    worker_name: str,
    run_once: RunOnceCallable,
    interval_seconds: int,
    kwargs: dict[str, Any],
) -> None:
    logger.info(
        "worker daemon started worker={} interval_seconds={} kwargs={}",
        worker_name,
        interval_seconds,
        kwargs,
    )

    while True:
        started = perf_counter()
        try:
            processed = await run_once(**kwargs)
            duration_ms = (perf_counter() - started) * 1000
            logger.info(
                "worker iteration finished worker={} processed={} duration_ms={:.2f}",
                worker_name,
                processed,
                duration_ms,
            )
        except Exception:
            logger.exception("worker iteration failed worker={}", worker_name)
            duration_ms = (perf_counter() - started) * 1000

        sleep_seconds = max(0.0, float(interval_seconds) - (duration_ms / 1000.0))
        await asyncio.sleep(sleep_seconds)


async def _run_once(
    worker_name: str,
    run_once: RunOnceCallable,
    kwargs: dict[str, Any],
) -> None:
    processed = await run_once(**kwargs)
    logger.info("worker one-shot finished worker={} processed={}", worker_name, processed)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a glass-factory worker in loop mode")
    parser.add_argument("--worker", required=True, choices=sorted(WORKERS.keys()))
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--kwargs", default=None, help="JSON object passed to run_once")
    parser.add_argument("--once", action="store_true", help="Run one iteration and exit")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    spec = WORKERS[args.worker]

    custom_kwargs = _parse_kwargs(args.kwargs)
    kwargs = {**spec.default_kwargs, **custom_kwargs}
    interval_seconds = args.interval_seconds or spec.interval_seconds

    if args.once:
        await _run_once(args.worker, spec.run_once, kwargs)
        return

    await _run_worker_loop(args.worker, spec.run_once, interval_seconds, kwargs)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
