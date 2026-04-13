from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from infra.core.config import get_settings


def build_limiter() -> Limiter:
    settings = get_settings()
    storage_url = settings.rate_limit.storage_url.strip() or "memory://"
    return Limiter(
        key_func=get_remote_address,
        storage_uri=storage_url,
        key_prefix=settings.rate_limit.key_prefix,
        in_memory_fallback_enabled=settings.rate_limit.in_memory_fallback_enabled,
    )


limiter = build_limiter()
