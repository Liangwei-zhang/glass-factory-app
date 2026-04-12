from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.public_api.main import app
from apps.public_api.routers import customer_app as customer_app_router
from infra.db.session import get_db_session
from infra.security.auth import get_current_user
from infra.security.idempotency import get_redis as _unused_get_redis  # noqa: F401
from tests.support.order_inventory_flow import (
    build_order_inventory_harness,
    make_auth_user,
    serialize_test_order,
)


def _patch_customer_app(monkeypatch, harness) -> None:
    async def fake_ensure_product_inventory(_session, glass_type: str, thickness: str, quantity: int):
        _ = (glass_type, thickness, quantity)
        return SimpleNamespace(id="product-1", product_name="Tempered Glass Panel")

    async def fake_serialize_order(_session, order, include_detail: bool = True, route_prefix: str = "/v1/app"):
        _ = (include_detail, route_prefix)
        return serialize_test_order(order)

    monkeypatch.setattr(customer_app_router, "orders_service", harness.orders_service)
    monkeypatch.setattr(
        customer_app_router.workspace_ui,
        "ensure_product_inventory",
        fake_ensure_product_inventory,
    )
    monkeypatch.setattr(customer_app_router.workspace_ui, "serialize_order", fake_serialize_order)


def test_customer_app_create_order_reserves_inventory(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_customer_app(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": "app-e2e-create"},
                data={
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Customer app order",
                },
                files={},
            )

            assert response.status_code == 200
            order_payload = response.json()["data"]["order"]
            assert order_payload["status"] == "pending"
            assert order_payload["totalQuantity"] == 3
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3
    finally:
        app.dependency_overrides.clear()


def test_customer_app_duplicate_create_is_rejected_without_extra_reserve(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_customer_app(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            payload = {
                "glassType": "Tempered",
                "thickness": "6mm",
                "quantity": "3",
                "priority": "normal",
                "estimatedCompletionDate": "2026-04-12",
                "specialInstructions": "Customer app order",
            }
            first_response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": "app-e2e-duplicate"},
                data=payload,
                files={},
            )
            second_response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": "app-e2e-duplicate"},
                data=payload,
                files={},
            )

            assert first_response.status_code == 200
            assert second_response.status_code == 409
            assert len(harness.orders_repository.orders_by_id) == 1
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3
    finally:
        app.dependency_overrides.clear()


def test_customer_viewer_cannot_create_orders(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_customer_app(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(
            role="customer_viewer",
            scopes=["orders:read", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": "app-e2e-viewer-create"},
                data={
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Customer app order",
                },
                files={},
            )

            assert response.status_code == 403
            assert len(harness.orders_repository.orders_by_id) == 0
            assert harness.inventory_row.available_qty == 10
            assert harness.inventory_row.reserved_qty == 0
    finally:
        app.dependency_overrides.clear()


def test_customer_app_create_requires_idempotency_key(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_customer_app(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/app/orders",
                data={
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Customer app order",
                },
                files={},
            )

            assert response.status_code == 400
            payload = response.json()
            assert payload["error"]["message"] == "Idempotency-Key header is required for write operations."
            assert len(harness.orders_repository.orders_by_id) == 0
            assert harness.inventory_row.available_qty == 10
            assert harness.inventory_row.reserved_qty == 0
    finally:
        app.dependency_overrides.clear()
