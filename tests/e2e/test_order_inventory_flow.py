from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.public_api.main import app
from apps.public_api.routers import orders as orders_router
from infra.db.models.finance import ReceivableModel
from infra.db.models.logistics import ShipmentModel
from infra.db.models.settings import EmailLogModel
from infra.db.session import get_db_session
from infra.security.auth import get_current_user
from infra.security.idempotency import get_redis as _unused_get_redis  # noqa: F401
from infra.security.rate_limit import limiter
from infra.storage.object_storage import ObjectStorage
from tests.support.order_inventory_flow import build_order_inventory_harness, make_auth_user


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state() -> None:
    limiter.reset()


def _drive_order_to_picked_up(client: TestClient, current_user: dict[str, object]) -> str:
    create_response = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": f"e2e-read-chain-create-{uuid4()}"},
        json={
            "customer_id": "cust-1",
            "delivery_address": "Factory pickup",
            "expected_delivery_date": "2026-04-12T10:00:00Z",
            "priority": "normal",
            "remark": "Read chain E2E order",
            "items": [
                {
                    "product_id": "product-1",
                    "product_name": "Tempered Glass Panel",
                    "glass_type": "Tempered",
                    "specification": "6mm",
                    "width_mm": 1200,
                    "height_mm": 800,
                    "quantity": 3,
                    "unit_price": "88.00",
                    "process_requirements": "temper",
                }
            ],
        },
    )

    assert create_response.status_code == 201
    order_id = create_response.json()["data"]["id"]

    entered_response = client.post(
        f"/v1/orders/{order_id}/entered",
        headers={"Idempotency-Key": f"e2e-read-chain-entered-{uuid4()}"},
    )
    assert entered_response.status_code == 200

    for step_key in ["cutting", "edging", "tempering", "finishing"]:
        if step_key == "tempering":
            current_user["value"] = make_auth_user(
                role="manager",
                scopes=["orders:read", "production:write"],
            )
        else:
            current_user["value"] = make_auth_user(
                scopes=["orders:read", "production:write"],
                stage=step_key,
            )
        step_response = client.post(
            f"/v1/orders/{order_id}/steps/{step_key}",
            headers={"Idempotency-Key": f"e2e-read-chain-{step_key}-{uuid4()}"},
            json={"action": "complete"},
        )
        assert step_response.status_code == 200

    current_user["value"] = make_auth_user(role="manager", scopes=["orders:read", "orders:write"])
    approve_response = client.post(
        f"/v1/orders/{order_id}/pickup/approve",
        headers={"Idempotency-Key": f"e2e-read-chain-approve-{uuid4()}"},
    )
    assert approve_response.status_code == 200

    current_user["value"] = make_auth_user(scopes=["orders:read", "orders:write"])
    signature_response = client.post(
        f"/v1/orders/{order_id}/pickup/signature",
        headers={"Idempotency-Key": f"e2e-read-chain-signature-{uuid4()}"},
        json={
            "signerName": "Alice Receiver",
            "signatureDataUrl": (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
            ),
        },
    )
    assert signature_response.status_code == 200

    return order_id


def _drive_order_to_ready_for_pickup(client: TestClient, current_user: dict[str, object]) -> str:
    create_response = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": f"e2e-direct-write-create-{uuid4()}"},
        json={
            "customer_id": "cust-1",
            "delivery_address": "Factory pickup",
            "expected_delivery_date": "2026-04-12T10:00:00Z",
            "priority": "normal",
            "remark": "Direct write chain E2E order",
            "items": [
                {
                    "product_id": "product-1",
                    "product_name": "Tempered Glass Panel",
                    "glass_type": "Tempered",
                    "specification": "6mm",
                    "width_mm": 1200,
                    "height_mm": 800,
                    "quantity": 3,
                    "unit_price": "88.00",
                    "process_requirements": "temper",
                }
            ],
        },
    )

    assert create_response.status_code == 201
    order_id = create_response.json()["data"]["id"]

    entered_response = client.post(
        f"/v1/orders/{order_id}/entered",
        headers={"Idempotency-Key": f"e2e-direct-write-entered-{uuid4()}"},
    )
    assert entered_response.status_code == 200

    for step_key in ["cutting", "edging", "tempering", "finishing"]:
        if step_key == "tempering":
            current_user["value"] = make_auth_user(
                role="manager",
                scopes=["orders:read", "production:write"],
            )
        else:
            current_user["value"] = make_auth_user(
                scopes=["orders:read", "production:write"],
                stage=step_key,
            )
        step_response = client.post(
            f"/v1/orders/{order_id}/steps/{step_key}",
            headers={"Idempotency-Key": f"e2e-direct-write-{step_key}-{uuid4()}"},
            json={"action": "complete"},
        )
        assert step_response.status_code == 200

    current_user["value"] = make_auth_user(role="manager", scopes=["orders:read", "orders:write"])
    approve_response = client.post(
        f"/v1/orders/{order_id}/pickup/approve",
        headers={"Idempotency-Key": f"e2e-direct-write-approve-{uuid4()}"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["status"] == "ready_for_pickup"

    return order_id


def test_orders_api_create_then_cancel_restores_inventory(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write", "orders:cancel"])

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-create-cancel"},
                json={
                    "customer_id": "cust-1",
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "E2E order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 3,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )

            assert create_response.status_code == 201
            order_payload = create_response.json()["data"]
            order_id = order_payload["id"]
            assert order_payload["status"] == "pending"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3

            cancel_response = client.post(
                f"/v1/orders/{order_id}/cancel",
                headers={"Idempotency-Key": "e2e-cancel"},
                json={"reason": "customer_changed_mind"},
            )

            assert cancel_response.status_code == 200
            cancelled_payload = cancel_response.json()["data"]
            assert cancelled_payload["status"] == "cancelled"
            assert harness.inventory_row.available_qty == 10
            assert harness.inventory_row.reserved_qty == 0
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_orders_api_create_then_confirm_deducts_inventory(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-create-confirm"},
                json={
                    "customer_id": "cust-1",
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "E2E order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 4,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )

            assert create_response.status_code == 201
            order_id = create_response.json()["data"]["id"]
            assert harness.inventory_row.available_qty == 6
            assert harness.inventory_row.reserved_qty == 4

            confirm_response = client.put(
                f"/v1/orders/{order_id}/confirm",
                headers={"Idempotency-Key": "e2e-confirm"},
            )

            assert confirm_response.status_code == 200
            confirmed_payload = confirm_response.json()["data"]
            assert confirmed_payload["status"] == "confirmed"
            assert harness.inventory_row.available_qty == 6
            assert harness.inventory_row.reserved_qty == 0
            assert harness.inventory_row.total_qty == 6
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_orders_api_create_then_entered_confirms_inventory(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-create-entered"},
                json={
                    "customer_id": "cust-1",
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "E2E order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 3,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )

            assert create_response.status_code == 201
            order_id = create_response.json()["data"]["id"]
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3

            entered_response = client.post(
                f"/v1/orders/{order_id}/entered",
                headers={"Idempotency-Key": "e2e-entered"},
            )

            assert entered_response.status_code == 200
            entered_payload = entered_response.json()["data"]
            assert entered_payload["status"] == "entered"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 0
            assert harness.inventory_row.total_qty == 7
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_orders_api_update_quantity_rebuilds_reservation(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-create-update"},
                json={
                    "customer_id": "cust-1",
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "E2E order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 3,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )

            assert create_response.status_code == 201
            order_payload = create_response.json()["data"]
            order_id = order_payload["id"]
            item_id = order_payload["items"][0]["id"]

            update_response = client.put(
                f"/v1/orders/{order_id}",
                headers={"Idempotency-Key": "e2e-update"},
                json={
                    "items": [
                        {
                            "id": item_id,
                            "quantity": 5,
                        }
                    ]
                },
            )

            assert update_response.status_code == 200
            updated_payload = update_response.json()["data"]
            assert updated_payload["total_quantity"] == 5
            assert updated_payload["items"][0]["quantity"] == 5
            assert harness.inventory_row.available_qty == 5
            assert harness.inventory_row.reserved_qty == 5
            assert harness.inventory_row.total_qty == 10
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_orders_api_duplicate_create_is_rejected_without_extra_reserve(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            payload = {
                "customer_id": "cust-1",
                "delivery_address": "Factory pickup",
                "expected_delivery_date": "2026-04-12T10:00:00Z",
                "priority": "normal",
                "remark": "E2E order",
                "items": [
                    {
                        "product_id": "product-1",
                        "product_name": "Tempered Glass Panel",
                        "glass_type": "Tempered",
                        "specification": "6mm",
                        "width_mm": 1200,
                        "height_mm": 800,
                        "quantity": 3,
                        "unit_price": "88.00",
                        "process_requirements": "temper",
                    }
                ],
            }
            first_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-duplicate-create"},
                json=payload,
            )
            second_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-duplicate-create"},
                json=payload,
            )

            assert first_response.status_code == 201
            assert second_response.status_code == 409
            assert len(harness.orders_repository.orders_by_id) == 1
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_orders_api_full_lifecycle_reaches_picked_up(monkeypatch, tmp_path: Path) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {
        "value": make_auth_user(scopes=["orders:read", "orders:write"]),
    }

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "object-storage"))
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": "e2e-full-lifecycle-create"},
                json={
                    "customer_id": "cust-1",
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "Full lifecycle E2E order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 3,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )

            assert create_response.status_code == 201
            order_payload = create_response.json()["data"]
            order_id = order_payload["id"]
            assert order_payload["status"] == "pending"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3
            assert len(harness.session.work_orders) == 1
            assert harness.session.work_orders[0].process_step_key == "cutting"

            entered_response = client.post(
                f"/v1/orders/{order_id}/entered",
                headers={"Idempotency-Key": "e2e-full-lifecycle-entered"},
            )

            assert entered_response.status_code == 200
            assert entered_response.json()["data"]["status"] == "entered"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 0

            for step_key in ["cutting", "edging", "tempering", "finishing"]:
                if step_key == "tempering":
                    current_user["value"] = make_auth_user(
                        role="manager",
                        scopes=["orders:read", "production:write"],
                    )
                else:
                    current_user["value"] = make_auth_user(
                        scopes=["orders:read", "production:write"],
                        stage=step_key,
                    )
                step_response = client.post(
                    f"/v1/orders/{order_id}/steps/{step_key}",
                    headers={"Idempotency-Key": f"e2e-full-lifecycle-{step_key}"},
                    json={"action": "complete"},
                )

                assert step_response.status_code == 200
                step_payload = step_response.json()["data"]
                assert step_payload["step_key"] == step_key
                assert step_payload["action"] == "complete"

            completed_order = harness.orders_repository.orders_by_id[order_id]
            assert completed_order.status == "completed"
            assert harness.session.work_orders[0].status == "completed"
            assert harness.session.work_orders[0].process_step_key == "finishing"

            current_user["value"] = make_auth_user(
                role="manager", scopes=["orders:read", "orders:write"]
            )
            approve_response = client.post(
                f"/v1/orders/{order_id}/pickup/approve",
                headers={"Idempotency-Key": "e2e-full-lifecycle-pickup-approve"},
            )

            assert approve_response.status_code == 200
            approved_payload = approve_response.json()["data"]
            assert approved_payload["status"] == "ready_for_pickup"
            assert approved_payload["pickup_approved_at"] is not None
            assert approved_payload["pickup_approved_by"] == "user-1"

            current_user["value"] = make_auth_user(scopes=["orders:read", "orders:write"])
            email_response = client.post(
                f"/v1/orders/{order_id}/pickup/send-email",
                headers={"Idempotency-Key": "e2e-full-lifecycle-pickup-email"},
            )

            assert email_response.status_code == 200
            email_payload = email_response.json()["data"]["emailLog"]
            assert email_payload["status"] == "preview"
            assert email_payload["transport"] == "log"
            assert email_payload["customerEmail"] == harness.customer.email
            email_logs = [row for row in harness.session.added if isinstance(row, EmailLogModel)]
            assert len(email_logs) == 1

            signature_response = client.post(
                f"/v1/orders/{order_id}/pickup/signature",
                headers={"Idempotency-Key": "e2e-full-lifecycle-pickup-signature"},
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )

            assert signature_response.status_code == 200
            picked_up_payload = signature_response.json()["data"]
            assert picked_up_payload["status"] == "picked_up"
            assert picked_up_payload["pickup_signer_name"] == "Alice Receiver"
            assert picked_up_payload["picked_up_at"] is not None
            assert picked_up_payload["pickup_signature_key"]

            duplicate_signature_response = client.post(
                f"/v1/orders/{order_id}/pickup/signature",
                headers={"Idempotency-Key": "e2e-full-lifecycle-pickup-signature-duplicate"},
                json={
                    "signerName": "Different Signer",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )

            assert duplicate_signature_response.status_code == 200
            duplicate_signature_payload = duplicate_signature_response.json()["data"]
            assert duplicate_signature_payload["status"] == "picked_up"
            assert duplicate_signature_payload["pickup_signer_name"] == "Alice Receiver"
            assert (
                duplicate_signature_payload["pickup_signature_key"]
                == picked_up_payload["pickup_signature_key"]
            )

            signature_path = ObjectStorage(
                base_dir=str(tmp_path / "object-storage")
            ).resolve_local_path(
                bucket="signatures",
                key=picked_up_payload["pickup_signature_key"],
            )
            assert signature_path.exists()
            shipments = [row for row in harness.session.added if isinstance(row, ShipmentModel)]
            assert len(shipments) == 1
            assert shipments[0].status == "delivered"
            assert shipments[0].receiver_name == "Alice Receiver"
            assert shipments[0].signature_image == picked_up_payload["pickup_signature_key"]
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_logistics_endpoints_surface_pickup_created_shipment(monkeypatch, tmp_path: Path) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {
        "value": make_auth_user(scopes=["orders:read", "orders:write"]),
    }

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "object-storage"))
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_picked_up(client, current_user)
            order_no = harness.orders_repository.orders_by_id[order_id].order_no

            shipments_response = client.get(
                "/v1/logistics/shipments",
                params={"order_id": order_id},
            )

            assert shipments_response.status_code == 200
            shipments_payload = shipments_response.json()["data"]
            assert len(shipments_payload) == 1
            assert shipments_payload[0]["order_id"] == order_id
            assert shipments_payload[0]["status"] == "delivered"
            assert shipments_payload[0]["tracking_no"] == order_no

            tracking_response = client.get(f"/v1/logistics/tracking/{order_no}")

            assert tracking_response.status_code == 200
            tracking_payload = tracking_response.json()["data"]
            assert tracking_payload["order_id"] == order_id
            assert tracking_payload["shipment_no"] == f"PK-{order_no}"
            assert tracking_payload["status"] == "delivered"
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_finance_endpoints_surface_receivable_for_completed_order(
    monkeypatch, tmp_path: Path
) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {
        "value": make_auth_user(scopes=["orders:read", "orders:write"]),
    }

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "object-storage"))
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_picked_up(client, current_user)
            harness.session.add(
                ReceivableModel(
                    id="recv-1",
                    order_id=order_id,
                    customer_id=harness.customer.id,
                    invoice_no="INV-1001",
                    amount=Decimal("264.00"),
                    paid_amount=Decimal("0.00"),
                    status="unpaid",
                    due_date=date(2026, 4, 30),
                )
            )

            receivables_response = client.get(
                "/v1/finance/receivables",
                params={"customer_id": harness.customer.id},
            )
            assert receivables_response.status_code == 200
            receivables_payload = receivables_response.json()["data"]
            assert len(receivables_payload) == 1
            assert receivables_payload[0]["order_id"] == order_id
            assert receivables_payload[0]["status"] == "unpaid"

            invoices_response = client.get(
                "/v1/finance/invoices",
                params={"customer_id": harness.customer.id},
            )
            assert invoices_response.status_code == 200
            invoices_payload = invoices_response.json()["data"]
            assert len(invoices_payload) == 1
            assert invoices_payload[0]["invoice_no"] == "INV-1001"
            assert invoices_payload[0]["amount"] == "264.00"

            statements_response = client.get(
                "/v1/finance/statements",
                params={"customer_id": harness.customer.id},
            )
            assert statements_response.status_code == 200
            statements_payload = statements_response.json()["data"]
            assert len(statements_payload) == 1
            assert statements_payload[0]["customer_id"] == harness.customer.id
            assert statements_payload[0]["paid_amount"] == "0.00"
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_logistics_and_finance_write_endpoints_cover_direct_flow(monkeypatch, tmp_path: Path) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {
        "value": make_auth_user(scopes=["orders:read", "orders:write"]),
    }

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "object-storage"))
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_ready_for_pickup(client, current_user)
            order_no = harness.orders_repository.orders_by_id[order_id].order_no

            current_user["value"] = make_auth_user(scopes=["orders:read", "logistics:write"])
            shipment_response = client.post(
                "/v1/logistics/shipments",
                headers={"Idempotency-Key": f"e2e-direct-shipment-create-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "carrier_name": "Factory Fleet",
                    "tracking_no": "TRACK-9002",
                    "vehicle_no": "TRK-02",
                    "driver_name": "Bob Driver",
                    "driver_phone": "+86-13900000001",
                    "shipped_at": "2026-04-12T10:00:00Z",
                },
            )

            assert shipment_response.status_code == 201
            shipment_payload = shipment_response.json()["data"]
            shipment_id = shipment_payload["id"]
            assert shipment_payload["order_id"] == order_id
            assert shipment_payload["status"] == "shipped"
            assert shipment_payload["tracking_no"] == "TRACK-9002"
            assert harness.session.shipments[0].shipment_no == f"SH-{order_no}"
            assert harness.orders_repository.orders_by_id[order_id].status == "shipping"

            current_user["value"] = make_auth_user(scopes=["orders:read"])
            shipments_response = client.get(
                "/v1/logistics/shipments",
                params={"order_id": order_id, "status": "shipped"},
            )
            assert shipments_response.status_code == 200
            shipments_payload = shipments_response.json()["data"]
            assert len(shipments_payload) == 1
            assert shipments_payload[0]["id"] == shipment_id

            current_user["value"] = make_auth_user(scopes=["orders:read", "logistics:write"])
            deliver_response = client.post(
                f"/v1/logistics/shipments/{shipment_id}/deliver",
                headers={"Idempotency-Key": f"e2e-direct-shipment-deliver-{uuid4()}"},
                json={
                    "receiver_name": "Carol Receiver",
                    "receiver_phone": "+86-13800000001",
                    "delivered_at": "2026-04-12T14:30:00Z",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )

            assert deliver_response.status_code == 200
            delivered_payload = deliver_response.json()["data"]
            assert delivered_payload["status"] == "delivered"
            assert delivered_payload["receiver_name"] == "Carol Receiver"
            assert delivered_payload["signature_image"]
            assert harness.session.shipments[0].status == "delivered"
            assert harness.session.shipments[0].signature_image == delivered_payload["signature_image"]
            assert harness.orders_repository.orders_by_id[order_id].status == "delivered"

            delivery_signature_path = ObjectStorage(
                base_dir=str(tmp_path / "object-storage")
            ).resolve_local_path(
                bucket="signatures",
                key=delivered_payload["signature_image"],
            )
            assert delivery_signature_path.exists()

            duplicate_deliver_response = client.post(
                f"/v1/logistics/shipments/{shipment_id}/deliver",
                headers={"Idempotency-Key": f"e2e-direct-shipment-deliver-dup-{uuid4()}"},
                json={
                    "receiver_name": "Other Receiver",
                    "receiver_phone": "+86-13800000009",
                    "delivered_at": "2026-04-12T16:00:00Z",
                },
            )

            assert duplicate_deliver_response.status_code == 200
            duplicate_delivered_payload = duplicate_deliver_response.json()["data"]
            assert duplicate_delivered_payload["status"] == "delivered"
            assert duplicate_delivered_payload["receiver_name"] == "Carol Receiver"
            assert harness.orders_repository.orders_by_id[order_id].status == "delivered"

            tracking_response = client.get("/v1/logistics/tracking/TRACK-9002")
            assert tracking_response.status_code == 200
            tracking_payload = tracking_response.json()["data"]
            assert tracking_payload["id"] == shipment_id
            assert tracking_payload["status"] == "delivered"

            current_user["value"] = make_auth_user(scopes=["orders:read", "finance:write"])
            receivable_response = client.post(
                "/v1/finance/receivables",
                headers={"Idempotency-Key": f"e2e-direct-receivable-create-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "due_date": "2026-04-30",
                    "amount": "450.50",
                    "invoice_no": "INV-45051",
                },
            )

            assert receivable_response.status_code == 201
            receivable_payload = receivable_response.json()["data"]
            receivable_id = receivable_payload["id"]
            assert receivable_payload["order_id"] == order_id
            assert receivable_payload["status"] == "unpaid"
            assert receivable_payload["amount"] == "450.50"

            current_user["value"] = make_auth_user(scopes=["orders:read"])
            receivables_response = client.get(
                "/v1/finance/receivables",
                params={"customer_id": harness.customer.id, "status": "unpaid"},
            )
            assert receivables_response.status_code == 200
            receivables_payload = receivables_response.json()["data"]
            assert len(receivables_payload) == 1
            assert receivables_payload[0]["id"] == receivable_id

            current_user["value"] = make_auth_user(scopes=["orders:read", "finance:write"])
            payment_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": f"e2e-direct-receivable-payment-{uuid4()}"},
                json={"amount": "450.50"},
            )

            assert payment_response.status_code == 200
            payment_payload = payment_response.json()["data"]
            assert payment_payload["status"] == "paid"
            assert payment_payload["paid_amount"] == "450.50"
            assert str(harness.session.receivables[0].paid_amount) == "450.50"

            refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"e2e-direct-receivable-refund-{uuid4()}"},
                json={"amount": "50.50"},
            )

            assert refund_response.status_code == 200
            refund_payload = refund_response.json()["data"]
            assert refund_payload["status"] == "partial"
            assert refund_payload["paid_amount"] == "400.00"

            over_refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"e2e-direct-receivable-over-refund-{uuid4()}"},
                json={"amount": "401.00"},
            )

            assert over_refund_response.status_code == 409
            assert over_refund_response.json()["error"]["message"] == "Refund exceeds paid amount."

            final_refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"e2e-direct-receivable-final-refund-{uuid4()}"},
                json={"amount": "400.00"},
            )

            assert final_refund_response.status_code == 200
            final_refund_payload = final_refund_response.json()["data"]
            assert final_refund_payload["status"] == "unpaid"
            assert final_refund_payload["paid_amount"] in {"0", "0.00"}
            assert str(harness.session.receivables[0].paid_amount) in {"0", "0.00"}

            invoices_response = client.get(
                "/v1/finance/invoices",
                params={"customer_id": harness.customer.id, "status": "unpaid"},
            )
            assert invoices_response.status_code == 200
            invoices_payload = invoices_response.json()["data"]
            assert len(invoices_payload) == 1
            assert invoices_payload[0]["invoice_no"] == "INV-45051"

            statements_response = client.get(
                "/v1/finance/statements",
                params={"customer_id": harness.customer.id},
            )
            assert statements_response.status_code == 200
            statements_payload = statements_response.json()["data"]
            assert len(statements_payload) == 1
            assert statements_payload[0]["paid_amount"] in {"0", "0.00"}
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()
