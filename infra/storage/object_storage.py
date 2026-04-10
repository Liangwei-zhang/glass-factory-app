from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(slots=True)
class StorageObject:
    bucket: str
    key: str
    size: int


class ObjectStorage:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(
            base_dir or os.getenv("OBJECT_STORAGE_LOCAL_DIR", "data/object_storage")
        )

    def _bucket_dir(self, bucket: str) -> Path:
        normalized_bucket = bucket.strip().strip("/")
        if not normalized_bucket:
            raise ValueError("bucket must not be empty")
        if any(part in {"", ".", ".."} for part in normalized_bucket.split("/")):
            raise ValueError("bucket must be a safe relative path")
        return self.base_dir / normalized_bucket

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized_key = key.strip().replace("\\", "/").lstrip("/")
        if not normalized_key:
            raise ValueError("key must not be empty")
        parts = normalized_key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("key must be a safe relative path")
        return "/".join(parts)

    def resolve_local_path(self, bucket: str, key: str) -> Path:
        normalized_key = self._normalize_key(key)
        return self._bucket_dir(bucket) / normalized_key

    async def put_bytes(self, bucket: str, key: str, payload: bytes) -> StorageObject:
        object_path = self.resolve_local_path(bucket, key)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        object_path.write_bytes(payload)
        logger.info(
            "Store object bucket={} key={} size={} path={}", bucket, key, len(payload), object_path
        )
        return StorageObject(bucket=bucket, key=key, size=len(payload))

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        object_path = self.resolve_local_path(bucket, key)
        return object_path.read_bytes()

    async def delete(self, bucket: str, key: str) -> None:
        object_path = self.resolve_local_path(bucket, key)
        if object_path.exists():
            object_path.unlink()
        logger.info("Delete object bucket={} key={} path={}", bucket, key, object_path)
