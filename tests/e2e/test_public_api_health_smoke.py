from __future__ import annotations

from fastapi.testclient import TestClient

from apps.public_api.main import app


def test_public_health_live_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == {"status": "alive"}
    assert payload["request_id"]
    assert payload["timestamp"]
