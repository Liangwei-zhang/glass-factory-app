from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from uuid import uuid4

from infra.core.errors import AppError, ErrorCode


def decode_signature_data_url(data_url: str) -> tuple[bytes, str]:
    raw = data_url.strip()
    if not raw.startswith("data:") or "," not in raw:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid signature payload.",
            status_code=400,
        )

    header, encoded = raw.split(",", maxsplit=1)
    extension = "png"
    if "image/jpeg" in header or "image/jpg" in header:
        extension = "jpg"

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid signature payload.",
            status_code=400,
        ) from exc

    return decoded, extension


def build_signature_storage_key(*, scope: str, entity_id: str, extension: str) -> str:
    now = datetime.now(timezone.utc)
    normalized_scope = scope.strip().strip("/") or "signatures"
    normalized_extension = extension.strip().lstrip(".") or "png"
    return (
        f"{normalized_scope}/{entity_id}/signatures/"
        f"{now:%Y%m%d%H%M%S}-{uuid4().hex}.{normalized_extension}"
    )
