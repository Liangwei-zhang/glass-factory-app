from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.responses import JSONResponse
from starlette.responses import Response

_EXCLUDED_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/admin/runtime/metrics",
)


def should_wrap_success_response(path: str, response: Response) -> bool:
    if response.status_code >= 400:
        return False
    if any(path.startswith(prefix) for prefix in _EXCLUDED_PATH_PREFIXES):
        return False

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return False

    return True


async def _read_response_body(response: Response) -> bytes | None:
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)

    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        return None

    chunks: list[bytes] = []
    async for chunk in body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
        elif isinstance(chunk, bytearray):
            chunks.append(bytes(chunk))
        else:
            chunks.append(str(chunk).encode("utf-8"))

    return b"".join(chunks)


def _passthrough_headers(response: Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }


def _rebuild_raw_json_response(response: Response, body: bytes) -> Response:
    return Response(
        status_code=response.status_code,
        content=body,
        media_type=response.media_type or "application/json",
        headers=_passthrough_headers(response),
    )


async def wrap_success_response(response: Response, request_id: str) -> Response:
    body = await _read_response_body(response)
    if body is None:
        return response

    try:
        payload = json.loads(body.decode("utf-8") or "null")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _rebuild_raw_json_response(response, body)

    if isinstance(payload, dict) and {"data", "request_id", "timestamp"}.issubset(payload.keys()):
        return _rebuild_raw_json_response(response, body)

    return JSONResponse(
        status_code=response.status_code,
        content={
            "data": payload,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers=_passthrough_headers(response),
    )
