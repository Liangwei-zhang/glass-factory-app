from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI

from apps.public_api.main import app


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


def test_public_sj_contract_routes_registered() -> None:
    route_map = _route_methods_map(app)

    required_routes = [
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/auth/logout"),
        ("POST", "/v1/auth/refresh"),
        ("POST", "/v1/auth/send-code"),
        ("POST", "/v1/orders"),
        ("GET", "/v1/orders"),
        ("GET", "/v1/orders/{order_id}"),
        ("PUT", "/v1/orders/{order_id}"),
        ("PUT", "/v1/orders/{order_id}/cancel"),
        ("POST", "/v1/orders/{order_id}/cancel"),
        ("PUT", "/v1/orders/{order_id}/confirm"),
        ("POST", "/v1/orders/{order_id}/entered"),
        ("POST", "/v1/orders/{order_id}/pickup/approve"),
        ("POST", "/v1/orders/{order_id}/pickup/signature"),
        ("POST", "/v1/orders/{order_id}/pickup/send-email"),
        ("POST", "/v1/orders/{order_id}/steps/{step_key}"),
        ("POST", "/v1/orders/{order_id}/drawing"),
        ("GET", "/v1/orders/{order_id}/drawing"),
        ("GET", "/v1/orders/{order_id}/export"),
        ("GET", "/v1/orders/{order_id}/timeline"),
        ("GET", "/v1/inventory"),
        ("GET", "/v1/inventory/{product_id}"),
        ("GET", "/v1/production/work-orders"),
        ("GET", "/v1/production/work-orders/{work_order_id}"),
        ("GET", "/v1/production/schedule"),
        ("GET", "/v1/customers/profile"),
        ("GET", "/v1/customers/credit"),
        ("GET", "/v1/logistics/shipments"),
        ("GET", "/v1/logistics/tracking/{no}"),
        ("GET", "/v1/finance/statements"),
        ("GET", "/v1/finance/invoices"),
        ("GET", "/v1/notifications"),
        ("PUT", "/v1/notifications/read"),
        ("GET", "/v1/search"),
    ]

    _assert_routes_exist(route_map, required_routes)
