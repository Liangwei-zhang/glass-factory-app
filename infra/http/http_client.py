from __future__ import annotations

from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def get_http_timeout() -> httpx.Timeout:
    return httpx.Timeout(timeout=5.0, connect=2.0)


def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=get_http_timeout())
