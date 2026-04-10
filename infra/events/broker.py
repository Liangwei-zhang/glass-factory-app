from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from loguru import logger

from infra.cache.redis_client import get_redis
from infra.core.config import get_settings


class EventBroker(Protocol):
    async def publish(self, topic: str, payload: dict, key: str | None = None) -> str: ...

    async def close(self) -> None: ...


class LoggingEventBroker:
    async def publish(self, topic: str, payload: dict, key: str | None = None) -> str:
        logger.info("Publish event topic={} key={} payload={}", topic, key, payload)
        return f"log:{topic}:{key or 'none'}"

    async def close(self) -> None:
        return None


class RedisStreamsEventBroker:
    def __init__(self, stream_key: str = "factory.events", maxlen: int = 50000) -> None:
        self.stream_key = stream_key
        self.maxlen = maxlen

    async def publish(self, topic: str, payload: dict, key: str | None = None) -> str:
        redis = await get_redis()
        fields: dict[str | int | float, str | int | float] = {
            "topic": topic,
            "payload": json.dumps(payload, ensure_ascii=True, default=str),
            "event_key": key or "",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        message_id = await redis.xadd(
            self.stream_key,
            cast(dict[Any, Any], fields),
            maxlen=self.maxlen,
            approximate=True,
        )
        return str(message_id)

    async def close(self) -> None:
        return None


class KafkaEventBroker:
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        client_id: str = "glass-factory-event-pipeline",
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.client_id = client_id
        self._producer: Any | None = None
        self._producer_lock = asyncio.Lock()

    async def _ensure_producer(self) -> Any:
        if self._producer is not None:
            return self._producer

        async with self._producer_lock:
            if self._producer is not None:
                return self._producer

            try:
                from aiokafka import AIOKafkaProducer
            except ModuleNotFoundError as exc:
                raise RuntimeError("aiokafka is required when EVENT_BROKER_BACKEND=kafka") from exc

            producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id=self.client_id,
            )
            await producer.start()
            self._producer = producer

        return self._producer

    async def publish(self, topic: str, payload: dict, key: str | None = None) -> str:
        producer = await self._ensure_producer()

        envelope = {
            "topic": topic,
            "payload": payload,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        value = json.dumps(envelope, ensure_ascii=True, default=str).encode("utf-8")
        key_bytes = key.encode("utf-8") if key is not None else None

        metadata = await producer.send_and_wait(
            topic=self.topic,
            value=value,
            key=key_bytes,
        )
        return f"{metadata.topic}:{metadata.partition}:{metadata.offset}"

    async def close(self) -> None:
        producer = self._producer
        self._producer = None
        if producer is not None:
            await producer.stop()


def build_event_broker() -> EventBroker:
    settings = get_settings()
    backend = settings.events.backend

    if backend in {"redis", "redis_stream", "redis_streams"}:
        return RedisStreamsEventBroker(
            stream_key=settings.events.redis_stream,
            maxlen=settings.events.redis_stream_maxlen,
        )

    if backend == "kafka":
        return KafkaEventBroker(
            bootstrap_servers=settings.events.kafka_bootstrap_servers,
            topic=settings.events.kafka_topic,
            client_id=settings.events.kafka_client_id,
        )

    if backend == "logging":
        return LoggingEventBroker()

    logger.warning(
        "Unknown event broker backend '{}' ; fallback to logging broker",
        backend,
    )
    return LoggingEventBroker()
