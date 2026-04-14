from __future__ import annotations

from infra.observability.runtime_probe import run_runtime_probe


async def test_runtime_probe_returns_expected_shape() -> None:
    result = await run_runtime_probe()

    assert result["status"] in {"ok", "degraded"}
    assert "checks" in result
    assert "database" in result["checks"]
    assert "redis" in result["checks"]
    assert "kafka" in result["checks"]
    assert "object_storage" in result["checks"]
