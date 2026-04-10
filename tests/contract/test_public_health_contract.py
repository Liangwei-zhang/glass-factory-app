from apps.public_api.main import app


def test_public_health_routes_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/v1/health/live" in paths
    assert "/v1/health/ready" in paths
