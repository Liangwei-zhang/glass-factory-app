from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from infra.core.config import get_settings


@dataclass(slots=True)
class StorageObject:
    bucket: str
    key: str
    size: int


class ObjectStorage:
    def __init__(self, base_dir: str | None = None) -> None:
        settings = get_settings().object_storage
        if base_dir is not None:
            self.backend = "local"
            self.base_dir = Path(base_dir)
        else:
            self.backend = os.getenv("OBJECT_STORAGE_BACKEND", settings.backend or "local").strip().lower()
            self.base_dir = Path(os.getenv("OBJECT_STORAGE_LOCAL_DIR", settings.local_dir))

        self.download_cache_dir = Path(
            os.getenv("OBJECT_STORAGE_DOWNLOAD_CACHE_DIR", settings.download_cache_dir)
        )
        self.s3_endpoint_url = os.getenv(
            "OBJECT_STORAGE_S3_ENDPOINT_URL",
            settings.s3_endpoint_url,
        )
        self.s3_region = os.getenv("OBJECT_STORAGE_S3_REGION", settings.s3_region)
        self.s3_access_key = os.getenv(
            "OBJECT_STORAGE_S3_ACCESS_KEY",
            settings.s3_access_key,
        )
        self.s3_secret_key = os.getenv(
            "OBJECT_STORAGE_S3_SECRET_KEY",
            settings.s3_secret_key,
        )
        self.s3_bucket = os.getenv("OBJECT_STORAGE_S3_BUCKET", settings.s3_bucket).strip()
        self.s3_prefix = os.getenv("OBJECT_STORAGE_S3_PREFIX", settings.s3_prefix).strip("/")
        self._s3_client: Any | None = None

    def _normalize_bucket(self, bucket: str) -> str:
        normalized_bucket = bucket.strip().strip("/")
        if not normalized_bucket:
            raise ValueError("bucket must not be empty")
        if any(part in {"", ".", ".."} for part in normalized_bucket.split("/")):
            raise ValueError("bucket must be a safe relative path")
        return normalized_bucket

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized_key = key.strip().replace("\\", "/").lstrip("/")
        if not normalized_key:
            raise ValueError("key must not be empty")
        parts = normalized_key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("key must be a safe relative path")
        return "/".join(parts)

    def _bucket_dir(self, bucket: str) -> Path:
        return self.base_dir / self._normalize_bucket(bucket)

    def resolve_local_path(self, bucket: str, key: str) -> Path:
        if self.backend != "local":
            raise RuntimeError("Local path resolution is only available for local object storage.")
        return self._bucket_dir(bucket) / self._normalize_key(key)

    def _remote_object_key(self, bucket: str, key: str) -> str:
        parts = [
            part
            for part in [self.s3_prefix, self._normalize_bucket(bucket), self._normalize_key(key)]
            if part
        ]
        return "/".join(parts)

    def _download_cache_path(self, bucket: str, key: str) -> Path:
        return self.download_cache_dir / self._remote_object_key(bucket, key)

    def _build_s3_client(self) -> Any:
        if self._s3_client is not None:
            return self._s3_client

        try:
            import boto3
            from botocore.config import Config
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "boto3 is required when OBJECT_STORAGE_BACKEND=s3."
            ) from exc

        self._s3_client = boto3.client(
            "s3",
            endpoint_url=self.s3_endpoint_url or None,
            aws_access_key_id=self.s3_access_key or None,
            aws_secret_access_key=self.s3_secret_key or None,
            region_name=self.s3_region or None,
            config=Config(s3={"addressing_style": "path"}),
        )
        return self._s3_client

    async def put_bytes(self, bucket: str, key: str, payload: bytes) -> StorageObject:
        if self.backend == "local":
            object_path = self.resolve_local_path(bucket=bucket, key=key)
            object_path.parent.mkdir(parents=True, exist_ok=True)
            object_path.write_bytes(payload)
            logger.info(
                "Store object bucket={} key={} size={} path={}",
                bucket,
                key,
                len(payload),
                object_path,
            )
            return StorageObject(bucket=bucket, key=key, size=len(payload))

        remote_key = self._remote_object_key(bucket, key)
        client = self._build_s3_client()

        def _upload() -> None:
            client.put_object(
                Bucket=self.s3_bucket,
                Key=remote_key,
                Body=payload,
                ContentLength=len(payload),
            )

        await asyncio.to_thread(_upload)
        logger.info(
            "Store object bucket={} key={} size={} remote_bucket={} remote_key={}",
            bucket,
            key,
            len(payload),
            self.s3_bucket,
            remote_key,
        )
        return StorageObject(bucket=bucket, key=key, size=len(payload))

    async def get_bytes(self, bucket: str, key: str) -> bytes:
        if self.backend == "local":
            return self.resolve_local_path(bucket=bucket, key=key).read_bytes()

        remote_key = self._remote_object_key(bucket, key)
        client = self._build_s3_client()

        def _download() -> bytes:
            response = client.get_object(Bucket=self.s3_bucket, Key=remote_key)
            return bytes(response["Body"].read())

        return await asyncio.to_thread(_download)

    async def exists(self, bucket: str, key: str) -> bool:
        if self.backend == "local":
            return self.resolve_local_path(bucket=bucket, key=key).exists()

        remote_key = self._remote_object_key(bucket, key)
        client = self._build_s3_client()

        def _head() -> bool:
            try:
                client.head_object(Bucket=self.s3_bucket, Key=remote_key)
                return True
            except Exception as exc:
                response = getattr(exc, "response", {}) or {}
                error = response.get("Error", {}) if isinstance(response, dict) else {}
                code = str(error.get("Code") or "")
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise

        return await asyncio.to_thread(_head)

    async def get_downloadable_path(self, bucket: str, key: str) -> Path:
        if self.backend == "local":
            return self.resolve_local_path(bucket=bucket, key=key)

        cache_path = self._download_cache_path(bucket, key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(await self.get_bytes(bucket, key))
        return cache_path

    async def is_available(self) -> bool:
        if self.backend == "local":
            try:
                self.base_dir.mkdir(parents=True, exist_ok=True)
                self.download_cache_dir.mkdir(parents=True, exist_ok=True)
                return True
            except Exception:
                return False

        if not self.s3_bucket:
            return False

        client = self._build_s3_client()

        def _head_bucket() -> bool:
            try:
                client.head_bucket(Bucket=self.s3_bucket)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_head_bucket)

    async def delete(self, bucket: str, key: str) -> None:
        if self.backend == "local":
            object_path = self.resolve_local_path(bucket=bucket, key=key)
            if object_path.exists():
                object_path.unlink()
            logger.info("Delete object bucket={} key={} path={}", bucket, key, object_path)
            return

        remote_key = self._remote_object_key(bucket, key)
        client = self._build_s3_client()

        def _delete() -> None:
            client.delete_object(Bucket=self.s3_bucket, Key=remote_key)

        await asyncio.to_thread(_delete)
        cache_path = self._download_cache_path(bucket, key)
        if cache_path.exists():
            cache_path.unlink()
        logger.info(
            "Delete object bucket={} key={} remote_bucket={} remote_key={}",
            bucket,
            key,
            self.s3_bucket,
            remote_key,
        )
