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
        ("POST", "/v1/logistics/shipments"),
        ("POST", "/v1/logistics/shipments/{shipment_id}/deliver"),
        ("GET", "/v1/logistics/tracking/{no}"),
        ("GET", "/v1/finance/statements"),
        ("GET", "/v1/finance/invoices"),
        ("GET", "/v1/finance/receivables"),
        ("POST", "/v1/finance/receivables"),
        ("POST", "/v1/finance/receivables/{receivable_id}/payments"),
        ("POST", "/v1/finance/receivables/{receivable_id}/refunds"),
        ("GET", "/v1/customers"),
        ("POST", "/v1/customers"),
        ("GET", "/v1/notifications"),
        ("PUT", "/v1/notifications/read"),
        ("POST", "/v1/workspace/auth/login"),
        ("GET", "/v1/workspace/me"),
        ("GET", "/v1/workspace/bootstrap"),
        ("GET", "/v1/workspace/customers"),
        ("POST", "/v1/workspace/customers"),
        ("PATCH", "/v1/workspace/customers/{customer_id}"),
        ("GET", "/v1/workspace/orders"),
        ("GET", "/v1/workspace/orders/{order_id}"),
        ("GET", "/v1/workspace/orders/{order_id}/drawing"),
        ("GET", "/v1/workspace/orders/{order_id}/export"),
        ("POST", "/v1/workspace/orders"),
        ("PUT", "/v1/workspace/orders/{order_id}"),
        ("POST", "/v1/workspace/orders/{order_id}/cancel"),
        ("POST", "/v1/workspace/orders/{order_id}/entered"),
        ("POST", "/v1/workspace/orders/{order_id}/steps/{step_key}"),
        ("POST", "/v1/workspace/orders/{order_id}/pickup/approve"),
        ("POST", "/v1/workspace/orders/{order_id}/pickup/send-email"),
        ("POST", "/v1/workspace/orders/{order_id}/pickup/signature"),
        ("GET", "/v1/workspace/shipments"),
        ("POST", "/v1/workspace/orders/{order_id}/shipment"),
        ("POST", "/v1/workspace/shipments/{shipment_id}/deliver"),
        ("GET", "/v1/workspace/receivables"),
        ("POST", "/v1/workspace/orders/{order_id}/receivable"),
        ("POST", "/v1/workspace/receivables/{receivable_id}/payments"),
        ("POST", "/v1/workspace/receivables/{receivable_id}/refunds"),
        ("GET", "/v1/workspace/notifications"),
        ("POST", "/v1/workspace/notifications/read"),
        ("GET", "/v1/workspace/settings/glass-types"),
        ("POST", "/v1/workspace/settings/glass-types"),
        ("PATCH", "/v1/workspace/settings/glass-types/{glass_type_id}"),
        ("GET", "/v1/workspace/settings/notification-templates/{template_key}"),
        ("PUT", "/v1/workspace/settings/notification-templates/{template_key}"),
        ("GET", "/v1/workspace/email-logs"),
        ("GET", "/v1/app/bootstrap"),
        ("GET", "/v1/app/orders"),
        ("GET", "/v1/app/orders/{order_id}"),
        ("POST", "/v1/app/orders"),
        ("GET", "/v1/app/profile"),
        ("GET", "/v1/app/credit"),
        ("GET", "/v1/app/notifications"),
        ("POST", "/v1/app/notifications/read"),
        ("GET", "/v1/search"),
    ]

    _assert_routes_exist(route_map, required_routes)
