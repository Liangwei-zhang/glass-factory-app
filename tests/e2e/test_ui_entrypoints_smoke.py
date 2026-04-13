from __future__ import annotations

from fastapi.testclient import TestClient

from apps.public_api.main import app

ENTRY_PATHS = ["/app", "/platform", "/admin"]


def test_ui_entrypoints_return_spa_html() -> None:
    with TestClient(app) as client:
        for path in ENTRY_PATHS:
            response = client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers.get("content-type", "")
            assert 'id="app"' in response.text
            if path == "/platform":
                assert "startLiveRefresh" in response.text
