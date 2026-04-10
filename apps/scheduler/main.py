from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from apps.workers.analytics_sink.main import run_once as run_analytics_sink
from apps.workers.cold_storage.main import run_once as run_cold_storage
from apps.workers.event_pipeline.main import run_once as run_event_pipeline
from apps.workers.inventory_sync.main import run_once as run_inventory_sync
from apps.workers.notification_dispatch.main import run_once as run_notification_dispatch
from apps.workers.order_timeout.main import run_once as run_order_timeout
from apps.workers.production_scheduler.main import run_once as run_production_scheduler
from apps.workers.retention.main import run_once as run_retention
from infra.core.config import get_settings

WorkerCallable = Callable[[], Awaitable[int]]


async def _run_job(name: str, worker: WorkerCallable) -> None:
    started = perf_counter()
    try:
        processed = await worker()
    except Exception:
        logger.exception("scheduler job failed job={}", name)
        return

    duration_ms = (perf_counter() - started) * 1000
    logger.info(
        "scheduler job completed job={} processed={} duration_ms={:.2f}",
        name,
        processed,
        duration_ms,
    )


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def heartbeat() -> None:
        logger.info("scheduler heartbeat")

    async def event_pipeline_job() -> None:
        await _run_job("event-pipeline", lambda: run_event_pipeline(batch_size=200))

    async def order_timeout_job() -> None:
        await _run_job("order-timeout", lambda: run_order_timeout(batch_size=200))

    async def inventory_sync_job() -> None:
        await _run_job("inventory-sync", lambda: run_inventory_sync(batch_size=500))

    async def production_scheduler_job() -> None:
        await _run_job("production-scheduler", lambda: run_production_scheduler(batch_size=200))

    async def notification_dispatch_job() -> None:
        await _run_job(
            "notification-dispatch",
            lambda: run_notification_dispatch(batch_size=200),
        )

    async def analytics_sink_job() -> None:
        await _run_job("analytics-sink", lambda: run_analytics_sink(batch_size=200))

    async def retention_job() -> None:
        await _run_job(
            "retention",
            lambda: run_retention(event_batch_size=500, notification_batch_size=500),
        )

    async def cold_storage_job() -> None:
        await _run_job("cold-storage", lambda: run_cold_storage(batch_size=200))

    scheduler.add_job(heartbeat, trigger="interval", minutes=1, id="heartbeat")
    if settings.scheduler.heartbeat_only:
        logger.info("scheduler heartbeat-only mode enabled")
        return scheduler

    scheduler.add_job(
        event_pipeline_job,
        trigger="interval",
        seconds=1,
        id="event-pipeline",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=10,
    )
    scheduler.add_job(
        order_timeout_job,
        trigger="interval",
        minutes=30,
        id="order-timeout",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        inventory_sync_job,
        trigger="interval",
        minutes=5,
        id="inventory-sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        production_scheduler_job,
        trigger="interval",
        minutes=15,
        id="production-scheduler",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        notification_dispatch_job,
        trigger="interval",
        seconds=30,
        id="notification-dispatch",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        analytics_sink_job,
        trigger="interval",
        minutes=2,
        id="analytics-sink",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        retention_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="retention",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        cold_storage_job,
        trigger="cron",
        hour=3,
        minute=0,
        id="cold-storage",
        max_instances=1,
        coalesce=True,
    )

    return scheduler


async def start_scheduler() -> AsyncIOScheduler:
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("scheduler started")
    return scheduler
