from __future__ import annotations

from infra.core.config import get_settings
from infra.events.broker import (
    KafkaEventBroker,
    LoggingEventBroker,
    RedisStreamsEventBroker,
    build_event_broker,
)


def _reset_settings_cache() -> None:
    get_settings.cache_clear()


def test_build_event_broker_redis_streams(monkeypatch) -> None:
    monkeypatch.setenv("EVENT_BROKER_BACKEND", "redis_streams")
    monkeypatch.setenv("EVENT_BROKER_REDIS_STREAM", "factory.events.test")
    _reset_settings_cache()

    broker = build_event_broker()

    assert isinstance(broker, RedisStreamsEventBroker)
    assert broker.stream_key == "factory.events.test"

    _reset_settings_cache()


def test_build_event_broker_kafka(monkeypatch) -> None:
    monkeypatch.setenv("EVENT_BROKER_BACKEND", "kafka")
    monkeypatch.setenv("EVENT_BROKER_KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("EVENT_BROKER_KAFKA_TOPIC", "factory.events")
    _reset_settings_cache()

    broker = build_event_broker()

    assert isinstance(broker, KafkaEventBroker)
    assert broker.bootstrap_servers == "kafka:9092"
    assert broker.topic == "factory.events"

    _reset_settings_cache()


def test_build_event_broker_unknown_fallback(monkeypatch) -> None:
    monkeypatch.setenv("EVENT_BROKER_BACKEND", "invalid-backend")
    _reset_settings_cache()

    broker = build_event_broker()

    assert isinstance(broker, LoggingEventBroker)

    _reset_settings_cache()
