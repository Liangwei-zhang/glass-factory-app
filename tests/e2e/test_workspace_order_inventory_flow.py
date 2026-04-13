from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.public_api.main import app
from apps.public_api.routers import workspace as workspace_router
from infra.db.models.logistics import ShipmentModel
from infra.db.models.settings import EmailLogModel
from infra.db.session import get_db_session
from infra.security.auth import get_current_user
from infra.security.idempotency import get_redis as _unused_get_redis  # noqa: F401
from infra.storage.object_storage import ObjectStorage
from tests.support.order_inventory_flow import (
    build_order_inventory_harness,
    make_auth_user,
    serialize_test_order,
)


def _patch_workspace_route(monkeypatch, harness) -> None:
    async def fake_ensure_product_inventory(
        _session, glass_type: str, thickness: str, quantity: int
    ):
        _ = (glass_type, thickness, quantity)
        return SimpleNamespace(id="product-1", product_name="Tempered Glass Panel")

    async def fake_serialize_workspace_order(
        _session, order_id: str, *, include_detail: bool = True
    ):
        _ = include_detail
        order = harness.orders_repository.orders_by_id[order_id]
        payload = serialize_test_order(order)
        payload["pickupSignatureUrl"] = (
            f"/v1/workspace/orders/{order.id}/pickup-signature"
            if order.pickup_signature_key
            else ""
        )
        return payload

    async def fake_get_order_model(_session, order_id: str, *, include_items: bool = True):
        _ = include_items
        return harness.orders_repository.orders_by_id[order_id]

    monkeypatch.setattr(workspace_router.workspace_orders, "orders_service", harness.orders_service)
    monkeypatch.setattr(
        workspace_router.workspace_orders.ui_support,
        "ensure_product_inventory",
        fake_ensure_product_inventory,
    )
    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "serialize_workspace_order",
        fake_serialize_workspace_order,
    )
    monkeypatch.setattr(workspace_router.workspace_orders, "get_order_model", fake_get_order_model)


def _drive_workspace_order_to_ready_for_pickup(
    client: TestClient, current_user: dict[str, object], harness
) -> str:
    create_response = client.post(
        "/v1/workspace/orders",
        headers={"Idempotency-Key": "workspace-e2e-ship-finance-create"},
        data={
            "customerId": harness.customer.id,
            "glassType": "Tempered",
            "thickness": "6mm",
            "quantity": "3",
            "priority": "normal",
            "estimatedCompletionDate": "2026-04-12",
            "specialInstructions": "Workspace shipping and finance e2e order",
        },
        files={},
    )

    assert create_response.status_code == 200
    order_id = create_response.json()["data"]["order"]["id"]

    entered_response = client.post(
        f"/v1/workspace/orders/{order_id}/entered",
        headers={"Idempotency-Key": "workspace-e2e-ship-finance-entered"},
    )
    assert entered_response.status_code == 200

    for step_key in ["cutting", "edging", "tempering", "finishing"]:
        if step_key == "tempering":
            current_user["value"] = make_auth_user(role="manager")
        else:
            current_user["value"] = make_auth_user(stage=step_key)
        step_response = client.post(
            f"/v1/workspace/orders/{order_id}/steps/{step_key}",
            headers={"Idempotency-Key": f"workspace-e2e-ship-finance-{step_key}"},
            json={"action": "complete"},
        )
        assert step_response.status_code == 200

    current_user["value"] = make_auth_user(role="manager")
    approve_response = client.post(
        f"/v1/workspace/orders/{order_id}/pickup/approve",
        headers={"Idempotency-Key": "workspace-e2e-ship-finance-pickup-approve"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["order"]["status"] == "ready_for_pickup"

    current_user["value"] = make_auth_user()
    return order_id


def test_workspace_orders_api_create_then_entered_confirms_inventory(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": "workspace-e2e-create-entered"},
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace e2e order",
                },
                files={},
            )

            assert create_response.status_code == 200
            order_payload = create_response.json()["data"]["order"]
            order_id = order_payload["id"]
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3

            entered_response = client.post(
                f"/v1/workspace/orders/{order_id}/entered",
                headers={"Idempotency-Key": "workspace-e2e-entered"},
            )

            assert entered_response.status_code == 200
            entered_payload = entered_response.json()["data"]["order"]
            assert entered_payload["status"] == "entered"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 0
            assert harness.inventory_row.total_qty == 7
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_api_update_quantity_rebuilds_reservation(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": "workspace-e2e-create-update"},
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace e2e order",
                },
                files={},
            )

            assert create_response.status_code == 200
            order_payload = create_response.json()["data"]["order"]
            order_id = order_payload["id"]

            update_response = client.put(
                f"/v1/workspace/orders/{order_id}",
                headers={"Idempotency-Key": "workspace-e2e-update"},
                data={"quantity": "5"},
                files={},
            )

            assert update_response.status_code == 200
            updated_payload = update_response.json()["data"]["order"]
            assert updated_payload["totalQuantity"] == 5
            assert updated_payload["items"][0]["quantity"] == 5
            assert harness.inventory_row.available_qty == 5
            assert harness.inventory_row.reserved_qty == 5
            assert harness.inventory_row.total_qty == 10
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_api_duplicate_create_is_rejected_without_extra_reserve(
    monkeypatch,
) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            payload = {
                "customerId": harness.customer.id,
                "glassType": "Tempered",
                "thickness": "6mm",
                "quantity": "3",
                "priority": "normal",
                "estimatedCompletionDate": "2026-04-12",
                "specialInstructions": "Workspace e2e order",
            }
            first_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": "workspace-e2e-duplicate"},
                data=payload,
                files={},
            )
            second_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": "workspace-e2e-duplicate"},
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


def test_workspace_orders_api_create_requires_idempotency_key(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/workspace/orders",
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace e2e order",
                },
                files={},
            )

            assert response.status_code == 400
            payload = response.json()
            assert (
                payload["error"]["message"]
                == "Idempotency-Key header is required for write operations."
            )
            assert len(harness.orders_repository.orders_by_id) == 0
            assert harness.inventory_row.available_qty == 10
            assert harness.inventory_row.reserved_qty == 0
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_api_full_lifecycle_reaches_picked_up(
    monkeypatch,
    tmp_path: Path,
) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)
    current_user = {"value": make_auth_user()}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_DIR", str(tmp_path / "object-storage"))
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": "workspace-e2e-full-lifecycle-create"},
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace full lifecycle e2e order",
                },
                files={},
            )

            assert create_response.status_code == 200
            order_payload = create_response.json()["data"]["order"]
            order_id = order_payload["id"]
            assert order_payload["status"] == "pending"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 3
            assert len(harness.session.work_orders) == 1
            assert harness.session.work_orders[0].process_step_key == "cutting"

            entered_response = client.post(
                f"/v1/workspace/orders/{order_id}/entered",
                headers={"Idempotency-Key": "workspace-e2e-full-lifecycle-entered"},
            )

            assert entered_response.status_code == 200
            assert entered_response.json()["data"]["order"]["status"] == "entered"
            assert harness.inventory_row.available_qty == 7
            assert harness.inventory_row.reserved_qty == 0

            for step_key in ["cutting", "edging", "tempering", "finishing"]:
                current_user["value"] = make_auth_user(stage=step_key)
                step_response = client.post(
                    f"/v1/workspace/orders/{order_id}/steps/{step_key}",
                    headers={"Idempotency-Key": f"workspace-e2e-full-lifecycle-{step_key}"},
                    json={"action": "complete"},
                )

                assert step_response.status_code == 200
                step_payload = step_response.json()["data"]
                assert step_payload["order"]["id"] == order_id
                assert step_payload["order"]["status"] in {"in_production", "completed"}

            completed_order = harness.orders_repository.orders_by_id[order_id]
            assert completed_order.status == "completed"
            assert harness.session.work_orders[0].status == "completed"
            assert harness.session.work_orders[0].process_step_key == "finishing"

            current_user["value"] = make_auth_user(role="manager")
            approve_response = client.post(
                f"/v1/workspace/orders/{order_id}/pickup/approve",
                headers={"Idempotency-Key": "workspace-e2e-full-lifecycle-pickup-approve"},
            )

            assert approve_response.status_code == 200
            approve_payload = approve_response.json()["data"]
            assert approve_payload["order"]["status"] == "ready_for_pickup"
            assert approve_payload["emailLog"]["status"] == "preview"
            assert approve_payload["emailLog"]["transport"] == "log"
            email_logs = [row for row in harness.session.added if isinstance(row, EmailLogModel)]
            assert len(email_logs) == 1

            current_user["value"] = make_auth_user()
            signature_response = client.post(
                f"/v1/workspace/orders/{order_id}/pickup/signature",
                headers={"Idempotency-Key": "workspace-e2e-full-lifecycle-pickup-signature"},
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )

            assert signature_response.status_code == 200
            signature_payload = signature_response.json()["data"]["order"]
            assert signature_payload["status"] == "picked_up"
            assert (
                signature_payload["pickupSignatureUrl"]
                == f"/v1/workspace/orders/{order_id}/pickup-signature"
            )

            picked_up_order = harness.orders_repository.orders_by_id[order_id]
            assert picked_up_order.pickup_signer_name == "Alice Receiver"
            assert picked_up_order.pickup_signature_key

            signature_path = ObjectStorage(
                base_dir=str(tmp_path / "object-storage")
            ).resolve_local_path(
                bucket="signatures",
                key=picked_up_order.pickup_signature_key,
            )
            assert signature_path.exists()
            shipments = [row for row in harness.session.added if isinstance(row, ShipmentModel)]
            assert len(shipments) == 1
            assert shipments[0].status == "delivered"
            assert shipments[0].receiver_name == "Alice Receiver"
            assert shipments[0].signature_image == picked_up_order.pickup_signature_key

            signature_download_response = client.get(
                f"/v1/workspace/orders/{order_id}/pickup-signature"
            )
            assert signature_download_response.status_code == 200
            assert signature_download_response.content == signature_path.read_bytes()

            pickup_export_response = client.get(
                f"/v1/workspace/orders/{order_id}/export",
                params={"document": "pickup"},
            )
            assert pickup_export_response.status_code == 200
            assert pickup_export_response.headers["content-type"] == "application/pdf"
            assert b"/Subtype /Image" in pickup_export_response.content
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_api_shipping_and_finance_flow(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)
    current_user = {"value": make_auth_user()}
    stored_signatures: list[tuple[str, str, bytes]] = []

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_put_bytes(self, *, bucket: str, key: str, payload: bytes):
        _ = self
        stored_signatures.append((bucket, key, payload))

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr("domains.logistics.service.ObjectStorage.put_bytes", fake_put_bytes)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_workspace_order_to_ready_for_pickup(client, current_user, harness)

            shipment_response = client.post(
                f"/v1/workspace/orders/{order_id}/shipment",
                headers={"Idempotency-Key": "workspace-e2e-shipment-create"},
                json={
                    "carrierName": "Factory Fleet",
                    "trackingNo": "TRACK-9001",
                    "vehicleNo": "TRK-01",
                    "driverName": "Bob Driver",
                    "driverPhone": "+86-13900000000",
                    "shippedAt": "2026-04-12T10:00:00Z",
                },
            )

            assert shipment_response.status_code == 200
            shipment_payload = shipment_response.json()["data"]["shipment"]
            shipment_id = shipment_payload["id"]
            assert shipment_payload["order_id"] == order_id
            assert shipment_payload["status"] == "shipped"
            assert shipment_payload["tracking_no"] == "TRACK-9001"
            assert shipment_payload["vehicle_no"] == "TRK-01"
            assert len(harness.session.shipments) == 1
            assert harness.session.shipments[0].driver_name == "Bob Driver"
            assert harness.orders_repository.orders_by_id[order_id].status == "shipping"

            shipments_response = client.get(
                "/v1/workspace/shipments",
                params={"order_id": order_id, "status": "shipped"},
            )

            assert shipments_response.status_code == 200
            shipments_payload = shipments_response.json()["data"]["shipments"]
            assert len(shipments_payload) == 1
            assert shipments_payload[0]["id"] == shipment_id

            deliver_response = client.post(
                f"/v1/workspace/shipments/{shipment_id}/deliver",
                headers={"Idempotency-Key": "workspace-e2e-shipment-deliver"},
                json={
                    "receiverName": "Carol Receiver",
                    "receiverPhone": "+86-13800000000",
                    "deliveredAt": "2026-04-12T14:30:00Z",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )

            assert deliver_response.status_code == 200
            delivered_payload = deliver_response.json()["data"]["shipment"]
            assert delivered_payload["status"] == "delivered"
            assert delivered_payload["receiver_name"] == "Carol Receiver"
            assert delivered_payload["signature_image"]
            assert harness.session.shipments[0].status == "delivered"
            assert harness.session.shipments[0].receiver_phone == "+86-13800000000"
            assert harness.session.shipments[0].signature_image == delivered_payload["signature_image"]
            assert harness.orders_repository.orders_by_id[order_id].status == "delivered"
            assert stored_signatures and stored_signatures[0][0] == "signatures"

            duplicate_deliver_response = client.post(
                f"/v1/workspace/shipments/{shipment_id}/deliver",
                headers={"Idempotency-Key": "workspace-e2e-shipment-deliver-duplicate"},
                json={
                    "receiverName": "Other Receiver",
                    "receiverPhone": "+86-13800000009",
                    "deliveredAt": "2026-04-12T15:30:00Z",
                },
            )

            assert duplicate_deliver_response.status_code == 200
            duplicate_delivered_payload = duplicate_deliver_response.json()["data"]["shipment"]
            assert duplicate_delivered_payload["status"] == "delivered"
            assert duplicate_delivered_payload["receiver_name"] == "Carol Receiver"
            assert harness.orders_repository.orders_by_id[order_id].status == "delivered"

            receivable_response = client.post(
                f"/v1/workspace/orders/{order_id}/receivable",
                headers={"Idempotency-Key": "workspace-e2e-receivable-create"},
                json={
                    "dueDate": "2026-04-30",
                    "amount": "450.50",
                    "invoiceNo": "INV-45050",
                },
            )

            assert receivable_response.status_code == 200
            receivable_payload = receivable_response.json()["data"]["receivable"]
            receivable_id = receivable_payload["id"]
            assert receivable_payload["order_id"] == order_id
            assert receivable_payload["status"] == "unpaid"
            assert receivable_payload["amount"] == "450.50"
            assert receivable_payload["due_date"] == "2026-04-30"
            assert len(harness.session.receivables) == 1
            assert str(harness.session.receivables[0].amount) == "450.50"

            receivables_response = client.get(
                "/v1/workspace/receivables",
                params={"customer_id": harness.customer.id, "status": "unpaid"},
            )

            assert receivables_response.status_code == 200
            receivables_payload = receivables_response.json()["data"]["receivables"]
            assert len(receivables_payload) == 1
            assert receivables_payload[0]["id"] == receivable_id

            payment_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": "workspace-e2e-receivable-payment"},
                json={"amount": "450.50"},
            )

            assert payment_response.status_code == 200
            payment_payload = payment_response.json()["data"]["receivable"]
            assert payment_payload["status"] == "paid"
            assert payment_payload["paid_amount"] == "450.50"
            assert str(harness.session.receivables[0].paid_amount) == "450.50"
            assert harness.session.receivables[0].status == "paid"

            refund_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": "workspace-e2e-receivable-refund"},
                json={"amount": "50.50"},
            )

            assert refund_response.status_code == 200
            refund_payload = refund_response.json()["data"]["receivable"]
            assert refund_payload["status"] == "partial"
            assert refund_payload["paid_amount"] == "400.00"

            over_refund_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": "workspace-e2e-receivable-over-refund"},
                json={"amount": "401.00"},
            )

            assert over_refund_response.status_code == 409
            assert over_refund_response.json()["error"]["message"] == "Refund exceeds paid amount."

            final_refund_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": "workspace-e2e-receivable-final-refund"},
                json={"amount": "400.00"},
            )

            assert final_refund_response.status_code == 200
            final_refund_payload = final_refund_response.json()["data"]["receivable"]
            assert final_refund_payload["status"] == "unpaid"
            assert final_refund_payload["paid_amount"] in {"0", "0.00"}
            assert str(harness.session.receivables[0].paid_amount) in {"0", "0.00"}
            assert harness.session.receivables[0].status == "unpaid"
    finally:
        app.dependency_overrides.clear()


def test_workspace_inventory_manual_adjustment_updates_stock(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)
    monkeypatch.setattr(workspace_router, "inventory_service", harness.inventory_service)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            inbound_response = client.post(
                "/v1/workspace/inventory/adjustments",
                headers={"Idempotency-Key": "workspace-e2e-inventory-inbound"},
                json={
                    "productId": "product-1",
                    "direction": "in",
                    "quantity": 6,
                    "referenceNo": "PO-6001",
                    "reason": "manual inbound",
                },
            )

            assert inbound_response.status_code == 200
            inbound_payload = inbound_response.json()["data"]["inventory"]
            assert inbound_payload["available_qty"] == 16
            assert inbound_payload["reserved_qty"] == 0
            assert inbound_payload["total_qty"] == 16

            outbound_response = client.post(
                "/v1/workspace/inventory/adjustments",
                headers={"Idempotency-Key": "workspace-e2e-inventory-outbound"},
                json={
                    "productId": "product-1",
                    "direction": "out",
                    "quantity": 5,
                    "referenceNo": "SO-5002",
                    "reason": "manual outbound",
                },
            )

            assert outbound_response.status_code == 200
            outbound_payload = outbound_response.json()["data"]["inventory"]
            assert outbound_payload["available_qty"] == 11
            assert outbound_payload["reserved_qty"] == 0
            assert outbound_payload["total_qty"] == 11
    finally:
        app.dependency_overrides.clear()


def test_workspace_inventory_manual_adjustment_rejects_shortage(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_workspace_route(monkeypatch, harness)
    monkeypatch.setattr(workspace_router, "inventory_service", harness.inventory_service)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/workspace/inventory/adjustments",
                headers={"Idempotency-Key": "workspace-e2e-inventory-shortage"},
                json={
                    "productId": "product-1",
                    "direction": "out",
                    "quantity": 99,
                    "referenceNo": "SO-9999",
                    "reason": "manual outbound",
                },
            )

            assert response.status_code == 409
            assert response.json()["error"]["message"] == "库存不足，无法出库。"
    finally:
        app.dependency_overrides.clear()
