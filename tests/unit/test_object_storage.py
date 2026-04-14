from __future__ import annotations

import pytest

from infra.storage.object_storage import ObjectStorage


def test_resolve_local_path_rejects_parent_segments_in_key(tmp_path) -> None:
    storage = ObjectStorage(base_dir=str(tmp_path))

    with pytest.raises(ValueError, match="safe relative path"):
        storage.resolve_local_path(bucket="drawings", key="../escape.pdf")


def test_resolve_local_path_rejects_parent_segments_in_bucket(tmp_path) -> None:
    storage = ObjectStorage(base_dir=str(tmp_path))

    with pytest.raises(ValueError, match="safe relative path"):
        storage.resolve_local_path(bucket="../drawings", key="orders/1/drawing.pdf")


def test_resolve_local_path_normalizes_windows_separator(tmp_path) -> None:
    storage = ObjectStorage(base_dir=str(tmp_path))

    path = storage.resolve_local_path(
        bucket="drawings",
        key="orders\\abc\\drawing.pdf",
    )

    assert path == tmp_path / "drawings" / "orders" / "abc" / "drawing.pdf"


@pytest.mark.asyncio
async def test_local_object_storage_is_available(tmp_path) -> None:
    storage = ObjectStorage(base_dir=str(tmp_path / "storage"))

    assert await storage.is_available() is True
