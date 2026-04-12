from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI

from apps.admin_api.main import app


def _route_methods_map(target_app: FastAPI) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for route in target_app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path is None or methods is None:
            continue

        normalized_methods = {method for method in methods if method not in {"HEAD", "OPTIONS"}}
        if not normalized_methods:
            continue

        mapping.setdefault(path, set()).update(normalized_methods)

    return mapping


def _assert_routes_exist(
    route_map: dict[str, set[str]],
    required_routes: Iterable[tuple[str, str]],
) -> None:
    for method, path in required_routes:
        assert path in route_map
        assert method in route_map[path]


def test_admin_sj_contract_routes_registered() -> None:
    route_map = _route_methods_map(app)

    required_routes = [
        ("GET", "/v1/admin/health/live"),
        ("GET", "/v1/admin/health/ready"),
        ("GET", "/v1/admin/analytics/overview"),
        ("GET", "/v1/admin/analytics/production"),
        ("GET", "/v1/admin/analytics/sales"),
        ("GET", "/v1/admin/users"),
        ("PUT", "/v1/admin/users/{user_id}"),
        ("POST", "/v1/admin/users/bulk"),
        ("GET", "/v1/admin/operators"),
        ("POST", "/v1/admin/production/schedule"),
        ("GET", "/v1/admin/production/lines"),
        ("PUT", "/v1/admin/production/lines/{line_id}"),
        ("GET", "/v1/admin/runtime/health"),
        ("GET", "/v1/admin/runtime/probe"),
        ("GET", "/v1/admin/runtime/metrics"),
        ("GET", "/v1/admin/runtime/alerts"),
        ("GET", "/v1/admin/audit"),
        ("GET", "/v1/admin/audit/logs"),
        ("GET", "/v1/admin/tasks"),
        ("GET", "/v1/admin/acceptance"),
    ]

    _assert_routes_exist(route_map, required_routes)