from __future__ import annotations

import pytest

from domains.orders.service import (
    MAX_DRAWING_SIZE_BYTES,
    _validate_drawing_upload,
)
from infra.core.errors import AppError


def test_validate_drawing_upload_accepts_pdf_without_explicit_content_type() -> None:
    safe_name, content_type = _validate_drawing_upload(
        filename="shop-drawing.pdf",
        payload_bytes=b"%PDF-1.7\n",
        content_type=None,
    )

    assert safe_name == "shop-drawing.pdf"
    assert content_type == "application/pdf"


def test_validate_drawing_upload_rejects_unsupported_type() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate_drawing_upload(
            filename="script.exe",
            payload_bytes=b"not-a-drawing",
            content_type="application/octet-stream",
        )

    assert exc_info.value.message == "Only PDF, JPG, and PNG drawing files are supported."


def test_validate_drawing_upload_rejects_oversized_payload() -> None:
    with pytest.raises(AppError) as exc_info:
        _validate_drawing_upload(
            filename="too-large.pdf",
            payload_bytes=b"x" * (MAX_DRAWING_SIZE_BYTES + 1),
            content_type="application/pdf",
        )

    assert exc_info.value.message == "Drawing file must not exceed 50MB."
