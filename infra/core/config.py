from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_file_backed_value(env_name: str) -> str | None:
    file_key = f"{env_name}_FILE"
    file_path = os.getenv(file_key)
    if not file_path:
        return None

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Secret file does not exist: {file_path}")

    return path.read_text(encoding="utf-8").strip()


def env_or_file(env_name: str, default: str = "") -> str:
    file_value = _read_file_backed_value(env_name)
    if file_value is not None:
        return file_value
    return os.getenv(env_name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class DatabaseSettings(BaseModel):
    url: str = Field(
        default_factory=lambda: env_or_file(
            "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/glass_factory"
        )
    )
    echo: bool = Field(default_factory=lambda: env_bool("DATABASE_ECHO", False))
    use_null_pool: bool = Field(default_factory=lambda: env_bool("DATABASE_USE_NULL_POOL", True))
    auto_init_schema_on_startup: bool = Field(
        default_factory=lambda: env_bool("AUTO_INIT_SCHEMA_ON_STARTUP", True)
    )


class RedisSettings(BaseModel):
    url: str = Field(default_factory=lambda: env_or_file("REDIS_URL", "redis://localhost:6379/0"))
    max_connections: int = Field(
        default_factory=lambda: int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
    )


class EventBrokerSettings(BaseModel):
    backend: str = Field(
        default_factory=lambda: os.getenv("EVENT_BROKER_BACKEND", "redis_streams").strip().lower()
    )
    redis_stream: str = Field(
        default_factory=lambda: os.getenv("EVENT_BROKER_REDIS_STREAM", "factory.events").strip()
    )
    redis_stream_maxlen: int = Field(
        default_factory=lambda: int(os.getenv("EVENT_BROKER_REDIS_STREAM_MAXLEN", "50000"))
    )
    kafka_bootstrap_servers: str = Field(
        default_factory=lambda: os.getenv(
            "EVENT_BROKER_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        ).strip()
    )
    kafka_topic: str = Field(
        default_factory=lambda: os.getenv("EVENT_BROKER_KAFKA_TOPIC", "factory.events").strip()
    )
    kafka_client_id: str = Field(
        default_factory=lambda: os.getenv(
            "EVENT_BROKER_KAFKA_CLIENT_ID", "glass-factory-event-pipeline"
        ).strip()
    )


class AnalyticsSettings(BaseModel):
    clickhouse_base_url: str = Field(
        default_factory=lambda: env_or_file("CLICKHOUSE_BASE_URL", "http://localhost:8123")
    )
    clickhouse_database: str = Field(
        default_factory=lambda: env_or_file("CLICKHOUSE_DATABASE", "default")
    )


class RateLimitSettings(BaseModel):
    storage_url: str = Field(
        default_factory=lambda: env_or_file("RATE_LIMIT_STORAGE_URL", "memory://")
    )
    key_prefix: str = Field(
        default_factory=lambda: os.getenv("RATE_LIMIT_KEY_PREFIX", "glass-factory").strip()
    )
    in_memory_fallback_enabled: bool = Field(
        default_factory=lambda: env_bool("RATE_LIMIT_IN_MEMORY_FALLBACK_ENABLED", True)
    )


class SchedulerSettings(BaseModel):
    heartbeat_only: bool = Field(
        default_factory=lambda: env_bool("SCHEDULER_HEARTBEAT_ONLY", False)
    )


class SecuritySettings(BaseModel):
    jwt_secret: str = Field(
        default_factory=lambda: env_or_file("JWT_SECRET", "glass-factory-dev-secret")
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(
        default_factory=lambda: int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
    )


class SMTPSettings(BaseModel):
    host: str = Field(default_factory=lambda: env_or_file("SMTP_HOST", ""))
    port: int = Field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    secure: bool = Field(default_factory=lambda: env_bool("SMTP_SECURE", False))
    user: str = Field(default_factory=lambda: env_or_file("SMTP_USER", ""))
    password: str = Field(default_factory=lambda: env_or_file("SMTP_PASS", ""))
    from_address: str = Field(default_factory=lambda: env_or_file("SMTP_FROM", ""))


class ObjectStorageSettings(BaseModel):
    backend: str = Field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_BACKEND", "local").strip().lower()
    )
    local_dir: str = Field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_LOCAL_DIR", "data/object_storage")
    )
    download_cache_dir: str = Field(
        default_factory=lambda: os.getenv(
            "OBJECT_STORAGE_DOWNLOAD_CACHE_DIR",
            "data/object_storage_cache",
        )
    )
    s3_endpoint_url: str = Field(
        default_factory=lambda: env_or_file("OBJECT_STORAGE_S3_ENDPOINT_URL", "")
    )
    s3_region: str = Field(
        default_factory=lambda: env_or_file("OBJECT_STORAGE_S3_REGION", "us-east-1")
    )
    s3_access_key: str = Field(
        default_factory=lambda: env_or_file("OBJECT_STORAGE_S3_ACCESS_KEY", "")
    )
    s3_secret_key: str = Field(
        default_factory=lambda: env_or_file("OBJECT_STORAGE_S3_SECRET_KEY", "")
    )
    s3_bucket: str = Field(
        default_factory=lambda: env_or_file("OBJECT_STORAGE_S3_BUCKET", "glass-factory")
    )
    s3_prefix: str = Field(
        default_factory=lambda: os.getenv("OBJECT_STORAGE_S3_PREFIX", "").strip().strip("/")
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "glass-factory"
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "dev"))
    debug: bool = Field(default_factory=lambda: env_bool("APP_DEBUG", False))
    public_api_prefix: str = "/v1"
    admin_api_prefix: str = "/v1/admin"

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    events: EventBrokerSettings = Field(default_factory=EventBrokerSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    smtp: SMTPSettings = Field(default_factory=SMTPSettings)
    object_storage: ObjectStorageSettings = Field(default_factory=ObjectStorageSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
