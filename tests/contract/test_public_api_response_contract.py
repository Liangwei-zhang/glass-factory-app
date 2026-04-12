from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.public_api.main import app
from apps.public_api.routers import auth as auth_router
from apps.public_api.routers import customer_app as customer_app_router
from apps.public_api.routers import customers as customers_router
from apps.public_api.routers import finance as finance_router
from apps.public_api.routers import health as health_router
from apps.public_api.routers import inventory as inventory_router
from apps.public_api.routers import logistics as logistics_router
from apps.public_api.routers import notifications as notifications_router
from apps.public_api.routers import orders as orders_router
from apps.public_api.routers import production as production_router
from apps.public_api.routers import workspace as workspace_router
from domains.auth.schema import LoginResponse, LoginUser
from domains.customers.schema import CustomerCreditBalance, CustomerProfile
from domains.finance.schema import InvoiceView, ReceivableView, StatementView
from domains.inventory.schema import InventorySnapshot
from domains.logistics.schema import ShipmentView
from domains.notifications.schema import MarkNotificationsReadResult, NotificationView
from domains.production.schema import WorkOrderView
from infra.core.errors import AppError
from infra.db.models.events import EventOutboxModel
from infra.db.models.production import QualityCheckModel
from infra.db.session import get_db_session
from infra.security.auth import get_current_user
from infra.security.rate_limit import limiter
from tests.support.order_inventory_flow import build_order_inventory_harness, make_auth_user, serialize_test_order


@pytest.fixture(autouse=True)
def _reset_rate_limiter_state() -> None:
    limiter.reset()


def _assert_success_envelope(response, *, status_code: int) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert "data" in payload
    assert "request_id" in payload
    assert "timestamp" in payload
    assert response.headers["X-Request-ID"] == payload["request_id"]
    return payload["data"]


def _assert_error_envelope(
    response,
    *,
    status_code: int,
    code: str,
    message: str,
) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert "request_id" in payload
    assert "timestamp" in payload
    assert response.headers["X-Request-ID"] == payload["request_id"]
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == message
    return payload["error"]


class _ScalarRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _ScalarRowResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _ExecuteSession:
    def __init__(self, *, execute_results=None):
        self._execute_results = list(execute_results or [])

    async def execute(self, _statement):
        if not self._execute_results:
            raise AssertionError("Unexpected execute call in public contract test.")
        return self._execute_results.pop(0)


def _patch_session_event_queries(monkeypatch, session, *, event_rows=None) -> None:
    original_execute = session.execute
    rows = list(event_rows or [])

    async def execute_with_event_rows(statement):
        entity = None
        if getattr(statement, "column_descriptions", None):
            entity = statement.column_descriptions[0].get("entity")
        if entity is EventOutboxModel:
            return _ScalarRowsResult(rows)
        if entity is QualityCheckModel:
            return _ScalarRowsResult([])
        return await original_execute(statement)

    monkeypatch.setattr(session, "execute", execute_with_event_rows)


def _drive_order_to_ready_for_pickup(client: TestClient, current_user: dict[str, object], customer_id: str) -> str:
    create_response = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": f"contract-direct-create-{uuid4()}"},
        json={
            "customer_id": customer_id,
            "delivery_address": "Factory pickup",
            "expected_delivery_date": "2026-04-12T10:00:00Z",
            "priority": "normal",
            "remark": "Contract write-chain order",
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
    order_id = _assert_success_envelope(create_response, status_code=201)["id"]

    entered_response = client.post(
        f"/v1/orders/{order_id}/entered",
        headers={"Idempotency-Key": f"contract-direct-entered-{uuid4()}"},
    )
    _assert_success_envelope(entered_response, status_code=200)

    for step_key in ["cutting", "edging", "tempering", "finishing"]:
        current_user["value"] = make_auth_user(
            scopes=["orders:read", "production:write"],
            stage=step_key,
        )
        step_response = client.post(
            f"/v1/orders/{order_id}/steps/{step_key}",
            headers={"Idempotency-Key": f"contract-direct-{step_key}-{uuid4()}"},
            json={"action": "complete"},
        )
        _assert_success_envelope(step_response, status_code=200)

    current_user["value"] = make_auth_user(role="manager", scopes=["orders:read", "orders:write"])
    approve_response = client.post(
        f"/v1/orders/{order_id}/pickup/approve",
        headers={"Idempotency-Key": f"contract-direct-approve-{uuid4()}"},
    )
    approve_payload = _assert_success_envelope(approve_response, status_code=200)
    assert approve_payload["status"] == "ready_for_pickup"
    return order_id


def _create_contract_order(client: TestClient, customer_id: str) -> dict:
    create_response = client.post(
        "/v1/orders",
        headers={"Idempotency-Key": f"contract-orders-read-{uuid4()}"},
        json={
            "customer_id": customer_id,
            "delivery_address": "Factory pickup",
            "expected_delivery_date": "2026-04-12T10:00:00Z",
            "priority": "normal",
            "remark": "Contract order read",
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
    return _assert_success_envelope(create_response, status_code=201)


def _patch_workspace_route(monkeypatch, harness) -> None:
    async def fake_ensure_product_inventory(_session, glass_type: str, thickness: str, quantity: int):
        _ = (glass_type, thickness, quantity)
        return SimpleNamespace(id="product-1", product_name="Tempered Glass Panel")

    async def fake_serialize_workspace_order(_session, order_id: str, *, include_detail: bool = True):
        _ = include_detail
        return serialize_test_order(harness.orders_repository.orders_by_id[order_id])

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


def _make_customer_profile(harness) -> CustomerProfile:
    return CustomerProfile.model_validate(harness.customer)


def _make_customer_credit(harness) -> CustomerCreditBalance:
    available = harness.customer.credit_limit - harness.customer.credit_used
    return CustomerCreditBalance(
        customer_id=harness.customer.id,
        credit_limit=harness.customer.credit_limit,
        credit_used=harness.customer.credit_used,
        available_credit=available,
    )


def _make_notification(user_id: str, *, is_read: bool = False) -> NotificationView:
    return NotificationView(
        id=f"notif-{uuid4()}",
        user_id=user_id,
        order_id=None,
        title="Ready for pickup",
        message="Your order is ready.",
        severity="info",
        is_read=is_read,
        created_at=datetime.now(timezone.utc),
    )


def test_orders_create_response_contract_and_duplicate_error(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            payload = {
                "customer_id": harness.customer.id,
                "delivery_address": "Factory pickup",
                "expected_delivery_date": "2026-04-12T10:00:00Z",
                "priority": "normal",
                "remark": "Contract order create",
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
            idempotency_key = f"contract-orders-create-{uuid4()}"

            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )

            create_payload = _assert_success_envelope(create_response, status_code=201)
            assert create_payload["status"] == "pending"
            assert create_payload["customer_id"] == harness.customer.id
            assert create_payload["total_quantity"] == 3
            assert len(create_payload["items"]) == 1

            duplicate_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )

            duplicate_payload = _assert_error_envelope(
                duplicate_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Duplicate write request.",
            )
            assert duplicate_payload["details"]["namespace"] == "orders:create"
            assert duplicate_payload["details"]["idempotency_key"] == idempotency_key
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_workspace_orders_create_response_contract_and_missing_idempotency(monkeypatch) -> None:
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
            success_response = client.post(
                "/v1/workspace/orders",
                headers={"Idempotency-Key": f"contract-workspace-create-{uuid4()}"},
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace contract order",
                },
                files={},
            )

            success_payload = _assert_success_envelope(success_response, status_code=200)
            order_payload = success_payload["order"]
            assert order_payload["status"] == "pending"
            assert order_payload["totalQuantity"] == 3
            assert len(order_payload["items"]) == 1

            missing_key_response = client.post(
                "/v1/workspace/orders",
                data={
                    "customerId": harness.customer.id,
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Workspace contract order",
                },
                files={},
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:orders:create"
    finally:
        app.dependency_overrides.clear()


def test_orders_read_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_session_event_queries(monkeypatch, harness.session)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            list_response = client.get("/v1/orders")

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 1
            assert list_payload[0]["id"] == order_id
            assert list_payload[0]["order_no"] == create_payload["order_no"]
            assert list_payload[0]["customer_id"] == harness.customer.id
            assert list_payload[0]["total_quantity"] == 3
            assert list_payload[0]["items"][0]["product_id"] == "product-1"

            detail_response = client.get(f"/v1/orders/{order_id}")

            detail_payload = _assert_success_envelope(detail_response, status_code=200)
            assert detail_payload["id"] == order_id
            assert detail_payload["order_no"] == create_payload["order_no"]
            assert detail_payload["status"] == "pending"
            assert detail_payload["delivery_address"] == "Factory pickup"
            assert detail_payload["reservation_ids"]

            timeline_response = client.get(f"/v1/orders/{order_id}/timeline")

            timeline_payload = _assert_success_envelope(timeline_response, status_code=200)
            assert len(timeline_payload) == 1
            assert timeline_payload[0]["event"] == "orders.order.created"
            assert timeline_payload[0]["status"] == "created"
            assert timeline_payload[0]["details"]["order_no"] == create_payload["order_no"]
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_read_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_session_event_queries(monkeypatch, harness.session)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            list_response = client.get("/v1/workspace/orders")

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload["orders"]) == 1
            assert list_payload["orders"][0]["id"] == order_id
            assert list_payload["orders"][0]["orderNo"] == create_payload["order_no"]
            assert list_payload["orders"][0]["status"] == "received"
            assert list_payload["orders"][0]["quantity"] == 3
            assert list_payload["orders"][0]["customer"]["id"] == harness.customer.id

            detail_response = client.get(f"/v1/workspace/orders/{order_id}")

            detail_payload = _assert_success_envelope(detail_response, status_code=200)
            assert detail_payload["order"]["id"] == order_id
            assert detail_payload["order"]["orderNo"] == create_payload["order_no"]
            assert detail_payload["order"]["status"] == "received"
            assert detail_payload["order"]["quantity"] == 3
            assert detail_payload["order"]["customer"]["companyName"] == harness.customer.company_name
            assert len(detail_payload["order"]["steps"]) == 4
            assert detail_payload["order"]["timeline"] == []
            assert detail_payload["order"]["versionHistory"][0]["versionNumber"] == 1
    finally:
        app.dependency_overrides.clear()


def test_orders_raw_drawing_and_export_response_contracts(monkeypatch, tmp_path) -> None:
    session = SimpleNamespace()
    drawing_path = tmp_path / "drawing.pdf"
    drawing_bytes = b"%PDF-1.4 drawing contract\n"
    export_bytes = b"%PDF-1.4 export contract\n"
    drawing_path.write_bytes(drawing_bytes)
    order_state = {
        "value": SimpleNamespace(
            drawing_object_key="drawing/order-1.pdf",
            drawing_original_name="drawing.pdf",
        )
    }

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_order(_session, order_id: str):
        assert _session is session
        assert order_id == "order-1"
        return order_state["value"]

    async def fake_export_document_pdf(_session, *, order_id: str, document: str):
        assert _session is session
        assert order_id == "order-1"
        assert document == "pickup"
        return export_bytes

    def fake_resolve_local_path(self, *, bucket: str, key: str):
        _ = self
        assert bucket == "drawings"
        assert key == "drawing/order-1.pdf"
        return drawing_path

    monkeypatch.setattr(orders_router.service, "get_order", fake_get_order)
    monkeypatch.setattr(orders_router.service, "export_document_pdf", fake_export_document_pdf)
    monkeypatch.setattr(orders_router.ObjectStorage, "resolve_local_path", fake_resolve_local_path)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            drawing_response = client.get("/v1/orders/order-1/drawing")

            assert drawing_response.status_code == 200
            assert drawing_response.content == drawing_bytes
            assert drawing_response.headers["content-type"].startswith("application/pdf")
            assert "drawing.pdf" in drawing_response.headers["content-disposition"]
            assert drawing_response.headers["X-Request-ID"]

            export_response = client.get("/v1/orders/order-1/export", params={"document": "pickup"})

            assert export_response.status_code == 200
            assert export_response.content == export_bytes
            assert export_response.headers["content-type"].startswith("application/pdf")
            assert 'filename="order-1-pickup.pdf"' in export_response.headers["content-disposition"]
            assert export_response.headers["X-Request-ID"]

            order_state["value"] = SimpleNamespace(
                drawing_object_key=None,
                drawing_original_name="drawing.pdf",
            )
            missing_drawing_response = client.get("/v1/orders/order-1/drawing")

            missing_drawing_payload = _assert_error_envelope(
                missing_drawing_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Drawing file is not uploaded.",
            )
            assert missing_drawing_payload["details"]["order_id"] == "order-1"
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_raw_drawing_and_export_response_contracts(monkeypatch, tmp_path) -> None:
    session = SimpleNamespace()
    drawing_path = tmp_path / "workspace-drawing.pdf"
    drawing_bytes = b"%PDF-1.4 workspace drawing\n"
    export_bytes = b"%PDF-1.4 workspace export\n"
    drawing_path.write_bytes(drawing_bytes)
    drawing_state = {"missing": False}

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_order_drawing_file(_session, order_id: str):
        assert _session is session
        assert order_id == "order-1"
        if drawing_state["missing"]:
            raise AppError(
                code="VALIDATION_ERROR",
                message="图纸不存在。",
                status_code=404,
                details={"order_id": order_id},
            )
        return drawing_path, "workspace-drawing.pdf"

    async def fake_export_workspace_order_document(_session, order_id: str, *, document: str = "order"):
        assert _session is session
        assert order_id == "order-1"
        assert document == "pickup"
        return export_bytes

    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "get_order_drawing_file",
        fake_get_order_drawing_file,
    )
    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "export_workspace_order_document",
        fake_export_workspace_order_document,
    )
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            drawing_response = client.get("/v1/workspace/orders/order-1/drawing")

            assert drawing_response.status_code == 200
            assert drawing_response.content == drawing_bytes
            assert drawing_response.headers["content-type"].startswith("application/pdf")
            assert "workspace-drawing.pdf" in drawing_response.headers["content-disposition"]
            assert drawing_response.headers["X-Request-ID"]

            export_response = client.get(
                "/v1/workspace/orders/order-1/export",
                params={"document": "pickup"},
            )

            assert export_response.status_code == 200
            assert export_response.content == export_bytes
            assert export_response.headers["content-type"].startswith("application/pdf")
            assert 'filename="order-1-pickup.pdf"' in export_response.headers["content-disposition"]
            assert export_response.headers["X-Request-ID"]

            drawing_state["missing"] = True
            missing_drawing_response = client.get("/v1/workspace/orders/order-1/drawing")

            missing_drawing_payload = _assert_error_envelope(
                missing_drawing_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="图纸不存在。",
            )
            assert missing_drawing_payload["details"] == {}
    finally:
        app.dependency_overrides.clear()


def test_orders_pickup_email_and_drawing_upload_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "orders:write"])

    async def fake_get_redis():
        return harness.redis

    async def fake_send_pickup_email(_session, order_id: str, actor_user_id: str):
        assert _session is harness.session
        assert actor_user_id == "user-1"
        return {
            "emailLog": {
                "id": "email-log-1",
                "templateKey": "ready_for_pickup",
                "orderId": order_id,
                "orderNo": "ORD-1001",
                "customerEmail": "alice@example.com",
                "subject": "订单 ORD-1001 已可取货",
                "body": "请安排到厂取货。",
                "status": "preview",
                "transport": "log",
                "errorMessage": "SMTP 未配置，邮件预览已保存。",
                "providerMessageId": "",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "sentAt": None,
            }
        }

    async def fake_upload_drawing(_session, order_id: str, filename: str, payload_bytes: bytes):
        assert _session is harness.session
        assert filename == "drawing.pdf"
        assert payload_bytes == b"drawing-payload"
        order = harness.orders_repository.orders_by_id[order_id]
        order.drawing_object_key = f"orders/{order_id}/drawings/drawing.pdf"
        order.drawing_original_name = filename
        return order

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(harness.orders_service, "send_pickup_email", fake_send_pickup_email)
    monkeypatch.setattr(harness.orders_service, "upload_drawing", fake_upload_drawing)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            missing_key_email_response = client.post(f"/v1/orders/{order_id}/pickup/send-email")
            missing_key_email_payload = _assert_error_envelope(
                missing_key_email_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_email_payload["details"]["namespace"] == "orders:pickup-send-email"

            email_response = client.post(
                f"/v1/orders/{order_id}/pickup/send-email",
                headers={"Idempotency-Key": f"contract-pickup-email-{uuid4()}"},
            )
            email_payload = _assert_success_envelope(email_response, status_code=200)
            assert email_payload["emailLog"]["orderId"] == order_id
            assert email_payload["emailLog"]["status"] == "preview"
            assert email_payload["emailLog"]["transport"] == "log"

            missing_key_drawing_response = client.post(
                f"/v1/orders/{order_id}/drawing",
                files={"drawing": ("drawing.pdf", b"drawing-payload", "application/pdf")},
            )
            missing_key_drawing_payload = _assert_error_envelope(
                missing_key_drawing_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_drawing_payload["details"]["namespace"] == "orders:upload-drawing"

            empty_drawing_response = client.post(
                f"/v1/orders/{order_id}/drawing",
                headers={"Idempotency-Key": f"contract-empty-drawing-{uuid4()}"},
                files={"drawing": ("drawing.pdf", b"", "application/pdf")},
            )
            empty_drawing_payload = _assert_error_envelope(
                empty_drawing_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Drawing file is empty.",
            )
            assert empty_drawing_payload["details"] == {}

            drawing_response = client.post(
                f"/v1/orders/{order_id}/drawing",
                headers={"Idempotency-Key": f"contract-upload-drawing-{uuid4()}"},
                files={"drawing": ("drawing.pdf", b"drawing-payload", "application/pdf")},
            )
            drawing_payload = _assert_success_envelope(drawing_response, status_code=200)
            assert drawing_payload["id"] == order_id
            assert drawing_payload["drawing_object_key"] == f"orders/{order_id}/drawings/drawing.pdf"
            assert drawing_payload["drawing_original_name"] == "drawing.pdf"
    finally:
        app.dependency_overrides.clear()


def test_workspace_pickup_send_email_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    current_user = {"value": make_auth_user(stage="cutting")}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_send_workspace_pickup_email(_session, *, order_id: str, actor_user_id: str):
        assert _session is harness.session
        assert order_id == "order-1"
        assert actor_user_id == "user-1"
        return {
            "emailLog": {
                "id": "workspace-email-log-1",
                "templateKey": "ready_for_pickup",
                "orderId": order_id,
                "orderNo": "ORD-1001",
                "customerEmail": "alice@example.com",
                "subject": "订单 ORD-1001 已可取货",
                "body": "请安排到厂取货。",
                "status": "preview",
                "transport": "log",
                "errorMessage": "SMTP 未配置，邮件预览已保存。",
                "providerMessageId": "",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "sentAt": None,
            }
        }

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "send_workspace_pickup_email",
        fake_send_workspace_pickup_email,
    )
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            forbidden_response = client.post(
                "/v1/workspace/orders/order-1/pickup/send-email",
                headers={"Idempotency-Key": f"contract-workspace-pickup-email-forbidden-{uuid4()}"},
            )
            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_payload["details"] == {}

            current_user["value"] = make_auth_user()

            missing_key_response = client.post("/v1/workspace/orders/order-1/pickup/send-email")
            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:orders:pickup-send-email"

            success_response = client.post(
                "/v1/workspace/orders/order-1/pickup/send-email",
                headers={"Idempotency-Key": f"contract-workspace-pickup-email-{uuid4()}"},
            )
            success_payload = _assert_success_envelope(success_response, status_code=200)
            assert success_payload["emailLog"]["id"] == "workspace-email-log-1"
            assert success_payload["emailLog"]["orderId"] == "order-1"
            assert success_payload["emailLog"]["status"] == "preview"
    finally:
        app.dependency_overrides.clear()


def test_orders_update_cancel_and_pickup_signature_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}
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

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr("domains.orders.service.ObjectStorage.put_bytes", fake_put_bytes)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]
            order_item_id = create_payload["items"][0]["id"]

            missing_key_update_response = client.put(
                f"/v1/orders/{order_id}",
                json={
                    "remark": "Updated contract order",
                    "items": [{"id": order_item_id, "quantity": 4}],
                },
            )
            missing_key_update_payload = _assert_error_envelope(
                missing_key_update_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_update_payload["details"]["namespace"] == "orders:update"

            update_response = client.put(
                f"/v1/orders/{order_id}",
                headers={"Idempotency-Key": f"contract-order-update-{uuid4()}"},
                json={
                    "remark": "Updated contract order",
                    "items": [{"id": order_item_id, "quantity": 4}],
                },
            )
            update_payload = _assert_success_envelope(update_response, status_code=200)
            assert update_payload["id"] == order_id
            assert update_payload["remark"] == "Updated contract order"
            assert update_payload["total_quantity"] == 4
            assert update_payload["items"][0]["quantity"] == 4

            missing_key_cancel_response = client.put(
                f"/v1/orders/{order_id}/cancel",
                json={"reason": "Customer cancelled"},
            )
            missing_key_cancel_payload = _assert_error_envelope(
                missing_key_cancel_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_cancel_payload["details"]["namespace"] == "orders:cancel"

            cancel_response = client.post(
                f"/v1/orders/{order_id}/cancel",
                headers={"Idempotency-Key": f"contract-order-cancel-{uuid4()}"},
                json={"reason": "Customer cancelled"},
            )
            cancel_payload = _assert_success_envelope(cancel_response, status_code=200)
            assert cancel_payload["id"] == order_id
            assert cancel_payload["status"] == "cancelled"

            signature_order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)
            current_user["value"] = make_auth_user(scopes=["orders:read", "orders:write"])

            missing_key_signature_response = client.post(
                f"/v1/orders/{signature_order_id}/pickup/signature",
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )
            missing_key_signature_payload = _assert_error_envelope(
                missing_key_signature_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_signature_payload["details"]["namespace"] == "orders:pickup-signature"

            signature_response = client.post(
                f"/v1/orders/{signature_order_id}/pickup/signature",
                headers={"Idempotency-Key": f"contract-pickup-signature-{uuid4()}"},
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )
            signature_payload = _assert_success_envelope(signature_response, status_code=200)
            assert signature_payload["id"] == signature_order_id
            assert signature_payload["status"] == "picked_up"
            assert signature_payload["pickup_signer_name"] == "Alice Receiver"
            assert signature_payload["pickup_signature_key"]
            assert stored_signatures and stored_signatures[0][0] == "signatures"
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_update_cancel_and_pickup_signature_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    current_user = {"value": make_auth_user(stage="cutting")}
    stored_signatures: list[tuple[str, str, bytes]] = []

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_get_order_model(_session, order_id: str, *, include_items: bool = True):
        _ = include_items
        assert _session is harness.session
        return harness.orders_repository.orders_by_id[order_id]

    async def fake_serialize_workspace_order(_session, order_id: str, *, include_detail: bool = True):
        _ = include_detail
        order = harness.orders_repository.orders_by_id[order_id]
        payload = serialize_test_order(order)
        payload["pickupSignerName"] = order.pickup_signer_name
        payload["pickupSignatureKey"] = order.pickup_signature_key
        return payload

    async def fake_put_bytes(self, *, bucket: str, key: str, payload: bytes):
        _ = self
        stored_signatures.append((bucket, key, payload))

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr(workspace_router.workspace_orders, "orders_service", harness.orders_service)
    monkeypatch.setattr(workspace_router.workspace_orders, "get_order_model", fake_get_order_model)
    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "serialize_workspace_order",
        fake_serialize_workspace_order,
    )
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr("domains.orders.service.ObjectStorage.put_bytes", fake_put_bytes)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            forbidden_update_response = client.put(
                f"/v1/workspace/orders/{order_id}",
                headers={"Idempotency-Key": f"contract-workspace-order-update-forbidden-{uuid4()}"},
                data={"quantity": "4"},
                files={},
            )
            forbidden_update_payload = _assert_error_envelope(
                forbidden_update_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_update_payload["details"] == {}

            current_user["value"] = make_auth_user()

            missing_key_update_response = client.put(
                f"/v1/workspace/orders/{order_id}",
                data={"quantity": "4", "specialInstructions": "Workspace updated"},
                files={},
            )
            missing_key_update_payload = _assert_error_envelope(
                missing_key_update_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_update_payload["details"]["namespace"] == "workspace:orders:update"

            update_response = client.put(
                f"/v1/workspace/orders/{order_id}",
                headers={"Idempotency-Key": f"contract-workspace-order-update-{uuid4()}"},
                data={"quantity": "4", "specialInstructions": "Workspace updated"},
                files={},
            )
            update_payload = _assert_success_envelope(update_response, status_code=200)
            assert update_payload["order"]["id"] == order_id
            assert update_payload["order"]["totalQuantity"] == 4

            missing_key_cancel_response = client.post(
                f"/v1/workspace/orders/{order_id}/cancel",
                json={"reason": "Customer cancelled"},
            )
            missing_key_cancel_payload = _assert_error_envelope(
                missing_key_cancel_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_cancel_payload["details"]["namespace"] == "workspace:orders:cancel"

            cancel_response = client.post(
                f"/v1/workspace/orders/{order_id}/cancel",
                headers={"Idempotency-Key": f"contract-workspace-order-cancel-{uuid4()}"},
                json={"reason": "Customer cancelled"},
            )
            cancel_payload = _assert_success_envelope(cancel_response, status_code=200)
            assert cancel_payload["order"]["id"] == order_id
            assert cancel_payload["order"]["status"] == "cancelled"

            signature_order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(stage="cutting")
            forbidden_signature_response = client.post(
                f"/v1/workspace/orders/{signature_order_id}/pickup/signature",
                headers={"Idempotency-Key": f"contract-workspace-signature-forbidden-{uuid4()}"},
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )
            forbidden_signature_payload = _assert_error_envelope(
                forbidden_signature_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_signature_payload["details"] == {}

            current_user["value"] = make_auth_user()

            missing_key_signature_response = client.post(
                f"/v1/workspace/orders/{signature_order_id}/pickup/signature",
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )
            missing_key_signature_payload = _assert_error_envelope(
                missing_key_signature_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_signature_payload["details"]["namespace"] == "workspace:orders:pickup-signature"

            signature_response = client.post(
                f"/v1/workspace/orders/{signature_order_id}/pickup/signature",
                headers={"Idempotency-Key": f"contract-workspace-signature-{uuid4()}"},
                json={
                    "signerName": "Alice Receiver",
                    "signatureDataUrl": (
                        "data:image/png;base64,"
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
                    ),
                },
            )
            signature_payload = _assert_success_envelope(signature_response, status_code=200)
            assert signature_payload["order"]["id"] == signature_order_id
            assert signature_payload["order"]["status"] == "picked_up"
            assert signature_payload["order"]["pickupSignerName"] == "Alice Receiver"
            assert signature_payload["order"]["pickupSignatureKey"]
            assert stored_signatures and stored_signatures[0][0] == "signatures"
    finally:
        app.dependency_overrides.clear()


def test_orders_confirm_entered_step_and_pickup_approve_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            missing_key_confirm_response = client.put(f"/v1/orders/{order_id}/confirm")
            missing_key_confirm_payload = _assert_error_envelope(
                missing_key_confirm_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_confirm_payload["details"]["namespace"] == "orders:confirm"

            confirm_response = client.put(
                f"/v1/orders/{order_id}/confirm",
                headers={"Idempotency-Key": f"contract-order-confirm-{uuid4()}"},
            )
            confirm_payload = _assert_success_envelope(confirm_response, status_code=200)
            assert confirm_payload["id"] == order_id
            assert confirm_payload["status"] == "confirmed"

            missing_key_entered_response = client.post(f"/v1/orders/{order_id}/entered")
            missing_key_entered_payload = _assert_error_envelope(
                missing_key_entered_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_entered_payload["details"]["namespace"] == "orders:entered"

            entered_response = client.post(
                f"/v1/orders/{order_id}/entered",
                headers={"Idempotency-Key": f"contract-order-entered-{uuid4()}"},
            )
            entered_payload = _assert_success_envelope(entered_response, status_code=200)
            assert entered_payload["id"] == order_id
            assert entered_payload["status"] == "entered"

            current_user["value"] = make_auth_user(
                scopes=["orders:read", "production:write"],
                stage="edging",
            )
            wrong_stage_response = client.post(
                f"/v1/orders/{order_id}/steps/cutting",
                headers={"Idempotency-Key": f"contract-order-step-wrong-stage-{uuid4()}"},
                json={"action": "complete"},
            )
            wrong_stage_payload = _assert_error_envelope(
                wrong_stage_response,
                status_code=403,
                code="FORBIDDEN",
                message="Operators can only operate orders in their own stage.",
            )
            assert wrong_stage_payload["details"]["operator_stage"] == "edging"
            assert wrong_stage_payload["details"]["requested_step"] == "cutting"

            current_user["value"] = make_auth_user(
                scopes=["orders:read", "production:write"],
                stage="cutting",
            )
            missing_key_step_response = client.post(
                f"/v1/orders/{order_id}/steps/cutting",
                json={"action": "complete"},
            )
            missing_key_step_payload = _assert_error_envelope(
                missing_key_step_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_step_payload["details"]["namespace"] == "orders:step-action"

            first_step_response = client.post(
                f"/v1/orders/{order_id}/steps/cutting",
                headers={"Idempotency-Key": f"contract-order-step-cutting-{uuid4()}"},
                json={"action": "complete"},
            )
            first_step_payload = _assert_success_envelope(first_step_response, status_code=200)
            assert first_step_payload["order_id"] == order_id
            assert first_step_payload["step_key"] == "cutting"
            assert first_step_payload["action"] == "complete"
            assert first_step_payload["status"] == "in_production"
            assert first_step_payload["updated_work_order_ids"]

            for step_key in ["edging", "tempering", "finishing"]:
                current_user["value"] = make_auth_user(
                    scopes=["orders:read", "production:write"],
                    stage=step_key,
                )
                step_response = client.post(
                    f"/v1/orders/{order_id}/steps/{step_key}",
                    headers={"Idempotency-Key": f"contract-order-step-{step_key}-{uuid4()}"},
                    json={"action": "complete"},
                )
                step_payload = _assert_success_envelope(step_response, status_code=200)
                assert step_payload["step_key"] == step_key
                assert step_payload["action"] == "complete"

            current_user["value"] = make_auth_user(role="manager", scopes=["orders:read", "orders:write"])
            missing_key_pickup_approve_response = client.post(
                f"/v1/orders/{order_id}/pickup/approve"
            )
            missing_key_pickup_approve_payload = _assert_error_envelope(
                missing_key_pickup_approve_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_pickup_approve_payload["details"]["namespace"] == "orders:pickup-approve"

            pickup_approve_response = client.post(
                f"/v1/orders/{order_id}/pickup/approve",
                headers={"Idempotency-Key": f"contract-order-pickup-approve-{uuid4()}"},
            )
            pickup_approve_payload = _assert_success_envelope(pickup_approve_response, status_code=200)
            assert pickup_approve_payload["id"] == order_id
            assert pickup_approve_payload["status"] == "ready_for_pickup"
            assert pickup_approve_payload["pickup_approved_by"] == "user-1"
            assert pickup_approve_payload["pickup_approved_at"] is not None
    finally:
        app.dependency_overrides.clear()


def test_workspace_orders_entered_step_and_pickup_approve_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    current_user = {"value": make_auth_user()}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_get_order_model(_session, order_id: str, *, include_items: bool = True):
        _ = include_items
        assert _session is harness.session
        return harness.orders_repository.orders_by_id[order_id]

    async def fake_serialize_workspace_order(_session, order_id: str, *, include_detail: bool = True):
        _ = include_detail
        order = harness.orders_repository.orders_by_id[order_id]
        payload = serialize_test_order(order)
        payload["pickupApprovedAt"] = (
            order.pickup_approved_at.isoformat() if order.pickup_approved_at is not None else None
        )
        payload["pickupApprovedBy"] = order.pickup_approved_by
        return payload

    async def fake_send_pickup_email(_session, order_id: str, actor_user_id: str):
        assert _session is harness.session
        assert actor_user_id == "user-1"
        return {
            "emailLog": {
                "id": "workspace-approve-email-1",
                "templateKey": "ready_for_pickup",
                "orderId": order_id,
                "orderNo": harness.orders_repository.orders_by_id[order_id].order_no,
                "customerEmail": "alice@example.com",
                "subject": "订单已可取货",
                "body": "请安排到厂取货。",
                "status": "preview",
                "transport": "log",
                "errorMessage": "SMTP 未配置，邮件预览已保存。",
                "providerMessageId": "",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "sentAt": None,
            }
        }

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr(workspace_router.workspace_orders, "orders_service", harness.orders_service)
    monkeypatch.setattr(workspace_router.workspace_orders, "get_order_model", fake_get_order_model)
    monkeypatch.setattr(
        workspace_router.workspace_orders,
        "serialize_workspace_order",
        fake_serialize_workspace_order,
    )
    monkeypatch.setattr(harness.orders_service, "send_pickup_email", fake_send_pickup_email)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            create_payload = _create_contract_order(client, harness.customer.id)
            order_id = create_payload["id"]

            current_user["value"] = make_auth_user(stage="cutting")
            forbidden_entered_response = client.post(
                f"/v1/workspace/orders/{order_id}/entered",
                headers={"Idempotency-Key": f"contract-workspace-entered-forbidden-{uuid4()}"},
            )
            forbidden_entered_payload = _assert_error_envelope(
                forbidden_entered_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_entered_payload["details"] == {}

            current_user["value"] = make_auth_user()
            missing_key_entered_response = client.post(f"/v1/workspace/orders/{order_id}/entered")
            missing_key_entered_payload = _assert_error_envelope(
                missing_key_entered_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_entered_payload["details"]["namespace"] == "workspace:orders:entered"

            entered_response = client.post(
                f"/v1/workspace/orders/{order_id}/entered",
                headers={"Idempotency-Key": f"contract-workspace-entered-{uuid4()}"},
            )
            entered_payload = _assert_success_envelope(entered_response, status_code=200)
            assert entered_payload["order"]["id"] == order_id
            assert entered_payload["order"]["status"] == "entered"

            forbidden_step_response = client.post(
                f"/v1/workspace/orders/{order_id}/steps/cutting",
                headers={"Idempotency-Key": f"contract-workspace-step-forbidden-{uuid4()}"},
                json={"action": "complete"},
            )
            forbidden_step_payload = _assert_error_envelope(
                forbidden_step_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_step_payload["details"] == {}

            current_user["value"] = make_auth_user(stage="cutting")
            missing_key_step_response = client.post(
                f"/v1/workspace/orders/{order_id}/steps/cutting",
                json={"action": "complete"},
            )
            missing_key_step_payload = _assert_error_envelope(
                missing_key_step_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_step_payload["details"]["namespace"] == "workspace:orders:step-action"

            first_step_response = client.post(
                f"/v1/workspace/orders/{order_id}/steps/cutting",
                headers={"Idempotency-Key": f"contract-workspace-step-cutting-{uuid4()}"},
                json={"action": "complete"},
            )
            first_step_payload = _assert_success_envelope(first_step_response, status_code=200)
            assert first_step_payload["order"]["id"] == order_id
            assert first_step_payload["order"]["status"] == "in_production"

            for step_key in ["edging", "tempering", "finishing"]:
                current_user["value"] = make_auth_user(stage=step_key)
                step_response = client.post(
                    f"/v1/workspace/orders/{order_id}/steps/{step_key}",
                    headers={"Idempotency-Key": f"contract-workspace-step-{step_key}-{uuid4()}"},
                    json={"action": "complete"},
                )
                step_payload = _assert_success_envelope(step_response, status_code=200)
                assert step_payload["order"]["id"] == order_id

            current_user["value"] = make_auth_user()
            forbidden_pickup_approve_response = client.post(
                f"/v1/workspace/orders/{order_id}/pickup/approve",
                headers={"Idempotency-Key": f"contract-workspace-pickup-approve-forbidden-{uuid4()}"},
            )
            forbidden_pickup_approve_payload = _assert_error_envelope(
                forbidden_pickup_approve_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_pickup_approve_payload["details"] == {}

            current_user["value"] = make_auth_user(role="manager")
            missing_key_pickup_approve_response = client.post(
                f"/v1/workspace/orders/{order_id}/pickup/approve"
            )
            missing_key_pickup_approve_payload = _assert_error_envelope(
                missing_key_pickup_approve_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert (
                missing_key_pickup_approve_payload["details"]["namespace"]
                == "workspace:orders:pickup-approve"
            )

            pickup_approve_response = client.post(
                f"/v1/workspace/orders/{order_id}/pickup/approve",
                headers={"Idempotency-Key": f"contract-workspace-pickup-approve-{uuid4()}"},
            )
            pickup_approve_payload = _assert_success_envelope(pickup_approve_response, status_code=200)
            assert pickup_approve_payload["order"]["id"] == order_id
            assert pickup_approve_payload["order"]["status"] == "ready_for_pickup"
            assert pickup_approve_payload["order"]["pickupApprovedBy"] == "user-1"
            assert pickup_approve_payload["order"]["pickupApprovedAt"] is not None
            assert pickup_approve_payload["emailLog"]["id"] == "workspace-approve-email-1"
            assert pickup_approve_payload["emailLog"]["orderId"] == order_id
            assert pickup_approve_payload["emailLog"]["status"] == "preview"
    finally:
        app.dependency_overrides.clear()


def test_customer_app_profile_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

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
            response = client.get("/v1/app/profile")

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["profile"]["id"] == harness.customer.id
            assert payload["profile"]["companyName"] == harness.customer.company_name
    finally:
        app.dependency_overrides.clear()


def test_auth_response_contracts_for_login_refresh_send_code_and_logout(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

    async def override_session() -> AsyncGenerator:
        yield SimpleNamespace()

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_get_redis():
        return harness.redis

    async def fake_login(_session, payload):
        assert payload.email == "customer@example.com"
        assert payload.password == "customer123"
        return LoginResponse(
            access_token="seed-token",
            expires_in=900,
            user=LoginUser(
                id=harness.user.id,
                username=harness.user.username,
                display_name=harness.user.display_name,
                role="customer",
                scopes=["orders:read", "orders:write", "finance:read"],
                customer_id=harness.customer.id,
                canonicalRole="customer",
                homePath="/app",
                shell="customer",
                canCreateOrders=True,
            ),
        )

    monkeypatch.setattr(auth_router.service, "login", fake_login)
    monkeypatch.setattr(auth_router, "get_redis", fake_get_redis)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            login_response = client.post(
                "/v1/auth/login",
                headers={"Idempotency-Key": f"contract-auth-login-{uuid4()}"},
                json={"email": "customer@example.com", "password": "customer123"},
            )

            login_payload = _assert_success_envelope(login_response, status_code=200)
            assert login_payload["access_token"]
            assert login_payload["refresh_token"]
            assert login_payload["user"]["id"] == harness.user.id
            assert login_payload["user"]["customerId"] == harness.customer.id
            assert login_payload["user"]["shell"] == "customer"

            refresh_token = login_payload["refresh_token"]
            refresh_response = client.post(
                "/v1/auth/refresh",
                headers={"Idempotency-Key": f"contract-auth-refresh-{uuid4()}"},
                json={"refreshToken": refresh_token},
            )

            refresh_payload = _assert_success_envelope(refresh_response, status_code=200)
            assert refresh_payload["access_token"]
            assert refresh_payload["refresh_token"] == refresh_token
            assert refresh_payload["token_type"] == "bearer"
            assert refresh_payload["expires_in"] == auth_router.settings.security.access_token_minutes * 60

            send_code_response = client.post(
                "/v1/auth/send-code",
                headers={"Idempotency-Key": f"contract-auth-send-code-{uuid4()}"},
                json={"target": "Customer@Example.com", "channel": "email"},
            )

            send_code_payload = _assert_success_envelope(send_code_response, status_code=200)
            assert send_code_payload == {
                "accepted": True,
                "channel": "email",
                "target": "Customer@Example.com",
                "expires_in": 300,
            }
            assert len(harness.redis.values["otp:email:customer@example.com"]) == 6

            logout_response = client.post(
                "/v1/auth/logout",
                headers={"Idempotency-Key": f"contract-auth-logout-{uuid4()}"},
                json={"refreshToken": refresh_token},
            )

            logout_payload = _assert_success_envelope(logout_response, status_code=200)
            assert logout_payload["success"] is True
            assert auth_router._refresh_session_key(refresh_token) not in harness.redis.values
    finally:
        app.dependency_overrides.clear()


def test_inventory_response_contracts_for_list_and_detail(monkeypatch) -> None:
    session = SimpleNamespace()
    snapshots = [
        InventorySnapshot(
            product_id="product-1",
            available_qty=8,
            reserved_qty=2,
            total_qty=10,
            safety_stock=1,
        ),
        InventorySnapshot(
            product_id="product-2",
            available_qty=5,
            reserved_qty=0,
            total_qty=5,
            safety_stock=0,
        ),
    ]

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["inventory:read"])

    async def fake_list_inventory(_session, *, product_ids: list[str] | None):
        assert _session is session
        assert product_ids == ["product-1", "product-2"]
        return snapshots

    async def fake_get_inventory_item(_session, *, product_id: str):
        assert _session is session
        assert product_id == "product-1"
        return snapshots[0]

    monkeypatch.setattr(inventory_router.service, "list_inventory", fake_list_inventory)
    monkeypatch.setattr(inventory_router.service, "get_inventory_item", fake_get_inventory_item)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/v1/inventory",
                params=[("product_ids", "product-1"), ("product_ids", "product-2")],
            )

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 2
            assert list_payload[0]["product_id"] == "product-1"
            assert list_payload[0]["available_qty"] == 8
            assert list_payload[1]["product_id"] == "product-2"

            detail_response = client.get("/v1/inventory/product-1")

            detail_payload = _assert_success_envelope(detail_response, status_code=200)
            assert detail_payload["product_id"] == "product-1"
            assert detail_payload["reserved_qty"] == 2
            assert detail_payload["total_qty"] == 10
    finally:
        app.dependency_overrides.clear()


def test_workspace_me_and_bootstrap_response_contracts(monkeypatch) -> None:
    session = SimpleNamespace()

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(role="operator", scopes=["orders:read", "customers:read"])

    async def fake_build_workspace_me(_session, auth_user):
        assert _session is session
        assert auth_user.role == "operator"
        return {
            "user": {
                "id": "user-1",
                "name": "Factory Operator",
                "email": "operator@example.com",
                "role": "operator",
                "scopes": ["orders:read", "customers:read"],
                "customerId": None,
                "stage": None,
                "stageLabel": None,
                "canonicalRole": "operator",
                "homePath": "/platform",
                "shell": "platform",
                "canCreateOrders": True,
            }
        }

    async def fake_build_workspace_bootstrap(_session, auth_user):
        assert _session is session
        assert auth_user.role == "operator"
        return {
            "user": {
                "id": "user-1",
                "name": "Factory Operator",
                "email": "operator@example.com",
                "role": "operator",
                "scopes": ["orders:read", "customers:read"],
                "customerId": None,
                "stage": None,
                "stageLabel": None,
                "canonicalRole": "operator",
                "homePath": "/platform",
                "shell": "platform",
                "canCreateOrders": True,
            },
            "options": {
                "glassTypes": ["Ultra Clear"],
                "thicknessOptions": ["6mm"],
                "priorities": ["normal", "rush"],
                "orderStatuses": ["pending", "shipping"],
                "productionSteps": [{"key": "cutting", "label": "Cutting"}],
            },
            "data": {
                "summary": {
                    "totalOrders": 1,
                    "activeOrders": 1,
                    "inProductionOrders": 0,
                    "readyForPickupOrders": 0,
                    "staleOrders": 0,
                    "rushOrders": 0,
                    "reworkOrders": 0,
                    "modifiedOrders": 0,
                    "activeCustomers": 1,
                },
                "orders": [{"id": "order-1", "status": "shipping"}],
                "customers": [{"id": "cust-1", "hasActiveOrders": True}],
                "notifications": [{"id": "notif-1", "title": "Queued"}],
            },
        }

    monkeypatch.setattr(workspace_router.workspace_session, "build_workspace_me", fake_build_workspace_me)
    monkeypatch.setattr(
        workspace_router.workspace_session,
        "build_workspace_bootstrap",
        fake_build_workspace_bootstrap,
    )
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            me_response = client.get("/v1/workspace/me")

            me_payload = _assert_success_envelope(me_response, status_code=200)
            assert me_payload["user"]["id"] == "user-1"
            assert me_payload["user"]["shell"] == "platform"

            bootstrap_response = client.get("/v1/workspace/bootstrap")

            bootstrap_payload = _assert_success_envelope(bootstrap_response, status_code=200)
            assert bootstrap_payload["options"]["glassTypes"] == ["Ultra Clear"]
            assert bootstrap_payload["data"]["summary"]["activeOrders"] == 1
            assert bootstrap_payload["data"]["orders"][0]["status"] == "shipping"
    finally:
        app.dependency_overrides.clear()


def test_workspace_auth_login_response_contract_and_missing_idempotency(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    session = SimpleNamespace()

    async def override_session() -> AsyncGenerator:
        yield session

    async def fake_get_redis():
        return harness.redis

    async def fake_login_workspace_user(_session, payload):
        assert _session is session
        assert payload == {"email": "operator@example.com", "password": "secret123"}
        return {
            "token": "workspace-token",
            "refreshToken": "workspace-refresh-token",
            "user": {
                "id": "user-1",
                "name": "Factory Operator",
                "email": "operator@example.com",
                "role": "operator",
                "scopes": ["orders:read", "customers:read"],
                "customerId": None,
                "stage": None,
                "stageLabel": None,
                "canonicalRole": "operator",
                "homePath": "/platform",
                "shell": "platform",
                "canCreateOrders": True,
            },
        }

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(
        workspace_router.workspace_session,
        "login_workspace_user",
        fake_login_workspace_user,
    )
    app.dependency_overrides[get_db_session] = override_session

    try:
        with TestClient(app) as client:
            missing_key_response = client.post(
                "/v1/workspace/auth/login",
                json={"email": "operator@example.com", "password": "secret123"},
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:auth:login"

            success_response = client.post(
                "/v1/workspace/auth/login",
                headers={"Idempotency-Key": f"contract-workspace-auth-login-{uuid4()}"},
                json={"email": "operator@example.com", "password": "secret123"},
            )

            success_payload = _assert_success_envelope(success_response, status_code=200)
            assert success_payload["token"] == "workspace-token"
            assert success_payload["refreshToken"] == "workspace-refresh-token"
            assert success_payload["user"]["shell"] == "platform"
    finally:
        app.dependency_overrides.clear()


def test_customer_app_bootstrap_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    session = _ExecuteSession(
        execute_results=[
            _ScalarRowsResult(
                [
                    SimpleNamespace(name="Low-E"),
                    SimpleNamespace(name="Ultra Clear"),
                ]
            )
        ]
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_load_customer_context(_session, auth_user):
        assert _session is session
        assert auth_user.customer_id == harness.customer.id
        return harness.user, harness.customer

    async def fake_ensure_default_glass_types(_session, user_id: str):
        assert _session is session
        assert user_id == harness.user.id

    async def fake_serialize_orders(_session, customer_id: str):
        assert _session is session
        assert customer_id == harness.customer.id
        return [
            {"id": "order-1", "status": "shipping"},
            {"id": "order-2", "status": "delivered"},
        ]

    async def fake_serialize_notifications(_session, user_id: str):
        assert _session is session
        assert user_id == harness.user.id
        return [{"id": "notif-1", "title": "Ready for pickup", "isRead": False}]

    monkeypatch.setattr(customer_app_router, "_load_customer_context", fake_load_customer_context)
    monkeypatch.setattr(
        customer_app_router.workspace_ui,
        "ensure_default_glass_types",
        fake_ensure_default_glass_types,
    )
    monkeypatch.setattr(customer_app_router, "_serialize_orders", fake_serialize_orders)
    monkeypatch.setattr(customer_app_router, "_serialize_notifications", fake_serialize_notifications)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/app/bootstrap")

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["user"]["customerId"] == harness.customer.id
            assert payload["options"]["glassTypes"] == ["Low-E", "Ultra Clear"]
            assert payload["data"]["summary"]["totalOrders"] == 2
            assert payload["data"]["summary"]["activeOrders"] == 1
            assert payload["data"]["summary"]["completedOrders"] == 1
            assert Decimal(str(payload["data"]["summary"]["availableCredit"])) == Decimal("100000.00")
            assert payload["data"]["notifications"][0]["id"] == "notif-1"
    finally:
        app.dependency_overrides.clear()


def test_customer_app_orders_notifications_and_credit_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_serialize_orders(_session, customer_id: str):
        assert _session is harness.session
        assert customer_id == harness.customer.id
        return [{"id": "order-1", "status": "shipping", "totalQuantity": 3}]

    async def fake_serialize_notifications(_session, user_id: str):
        assert _session is harness.session
        assert user_id == harness.user.id
        return [{"id": "notif-1", "title": "Ready for pickup", "isRead": False}]

    monkeypatch.setattr(customer_app_router, "_serialize_orders", fake_serialize_orders)
    monkeypatch.setattr(customer_app_router, "_serialize_notifications", fake_serialize_notifications)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            orders_response = client.get("/v1/app/orders")

            orders_payload = _assert_success_envelope(orders_response, status_code=200)
            assert orders_payload["orders"][0]["id"] == "order-1"
            assert orders_payload["orders"][0]["status"] == "shipping"

            notifications_response = client.get("/v1/app/notifications")

            notifications_payload = _assert_success_envelope(notifications_response, status_code=200)
            assert notifications_payload["notifications"][0]["id"] == "notif-1"
            assert notifications_payload["notifications"][0]["title"] == "Ready for pickup"

            credit_response = client.get("/v1/app/credit")

            credit_payload = _assert_success_envelope(credit_response, status_code=200)
            assert Decimal(str(credit_payload["credit"]["available"])) == Decimal("100000.00")
            assert Decimal(str(credit_payload["credit"]["used"])) == Decimal("0")
    finally:
        app.dependency_overrides.clear()


def test_customer_app_order_detail_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    order = SimpleNamespace(id="order-1", customer_id=harness.customer.id)
    session = SimpleNamespace()

    async def fake_execute(_statement):
        return _ScalarRowResult(order)

    async def override_session() -> AsyncGenerator:
        session.execute = fake_execute
        yield session

    async def override_current_user():
        return make_auth_user(
            role="customer",
            scopes=["orders:read", "orders:write", "finance:read"],
            customer_id=harness.customer.id,
        )

    async def fake_load_customer_context(_session, auth_user):
        assert _session is session
        assert auth_user.customer_id == harness.customer.id
        return harness.user, harness.customer

    async def fake_serialize_order(_session, order_model, include_detail: bool = True, route_prefix: str = "/v1/app"):
        assert _session is session
        assert order_model is order
        assert include_detail is True
        assert route_prefix == "/v1/app"
        return {"id": "order-1", "status": "shipping", "routePrefix": route_prefix}

    monkeypatch.setattr(customer_app_router, "_load_customer_context", fake_load_customer_context)
    monkeypatch.setattr(customer_app_router.workspace_ui, "serialize_order", fake_serialize_order)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/app/orders/order-1")

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["order"]["id"] == "order-1"
            assert payload["order"]["status"] == "shipping"
            assert payload["order"]["routePrefix"] == "/v1/app"
    finally:
        app.dependency_overrides.clear()


def test_customer_app_notifications_read_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

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

    async def fake_mark_notifications_read(_session, user_id: str):
        assert _session is harness.session
        assert user_id == harness.user.id
        return MarkNotificationsReadResult(updated_count=1)

    async def fake_serialize_notifications(_session, user_id: str):
        assert _session is harness.session
        assert user_id == harness.user.id
        return [{"id": "notif-1", "title": "Ready for pickup", "isRead": True}]

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(customer_app_router.notifications_service, "mark_notifications_read", fake_mark_notifications_read)
    monkeypatch.setattr(customer_app_router, "_serialize_notifications", fake_serialize_notifications)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            missing_key_response = client.post("/v1/app/notifications/read")

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "app:notifications:mark-read"

            success_response = client.post(
                "/v1/app/notifications/read",
                headers={"Idempotency-Key": f"contract-app-notifications-{uuid4()}"},
            )

            success_payload = _assert_success_envelope(success_response, status_code=200)
            assert success_payload["notifications"][0]["id"] == "notif-1"
            assert success_payload["notifications"][0]["isRead"] is True
    finally:
        app.dependency_overrides.clear()


def test_orders_create_supports_customer_portal_payload(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service

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

    async def fake_ensure_product_inventory(_session, glass_type: str, thickness: str, quantity: int):
        _ = (glass_type, thickness, quantity)
        return SimpleNamespace(id="product-1", product_name="Tempered Glass Panel")

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr(orders_router.workspace_ui, "ensure_product_inventory", fake_ensure_product_inventory)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            idempotency_key = f"contract-customer-direct-create-{uuid4()}"
            payload = {
                "glassType": "Tempered",
                "thickness": "6mm",
                "quantity": 3,
                "priority": "normal",
                "estimatedCompletionDate": "2026-04-12",
                "specialInstructions": "Customer direct contract order",
            }

            create_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )

            create_payload = _assert_success_envelope(create_response, status_code=201)
            assert create_payload["customer_id"] == harness.customer.id
            assert create_payload["status"] == "pending"
            assert create_payload["total_quantity"] == 3
            assert create_payload["items"][0]["product_id"] == "product-1"

            duplicate_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": idempotency_key},
                json=payload,
            )

            duplicate_payload = _assert_error_envelope(
                duplicate_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Duplicate write request.",
            )
            assert duplicate_payload["details"]["namespace"] == "orders:create"
            assert duplicate_payload["details"]["idempotency_key"] == idempotency_key
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_search_response_contract_for_empty_and_keyword() -> None:
    now = datetime.now(timezone.utc)
    session = _ExecuteSession(
        execute_results=[
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="order-1",
                        order_no="ORD-1001",
                        status="pending",
                        customer_id="cust-1",
                        created_at=now,
                    )
                ]
            ),
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="cust-1",
                        customer_code="CUST-1001",
                        company_name="Acme Glass",
                        contact_name="Alice",
                        phone="13800000000",
                        email="alice@example.com",
                    )
                ]
            ),
        ]
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read"])

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            empty_response = client.get("/v1/search")

            empty_payload = _assert_success_envelope(empty_response, status_code=200)
            assert empty_payload == {"keyword": "", "orders": [], "customers": []}

            keyword_response = client.get("/v1/search", params={"q": "glass", "limit": 5})

            keyword_payload = _assert_success_envelope(keyword_response, status_code=200)
            assert keyword_payload["keyword"] == "glass"
            assert keyword_payload["orders"][0]["order_no"] == "ORD-1001"
            assert keyword_payload["orders"][0]["customer_id"] == "cust-1"
            assert keyword_payload["customers"][0]["company_name"] == "Acme Glass"
            assert keyword_payload["customers"][0]["customer_code"] == "CUST-1001"
    finally:
        app.dependency_overrides.clear()


def test_public_health_response_contracts(monkeypatch) -> None:
    async def fake_run_runtime_probe():
        return {
            "status": "ok",
            "checks": {
                "database": {"status": "ok"},
                "redis": {"status": "ok"},
                "kafka": {"status": "degraded"},
            },
        }

    monkeypatch.setattr(health_router, "run_runtime_probe", fake_run_runtime_probe)

    with TestClient(app) as client:
        live_response = client.get("/v1/health/live")

        live_payload = _assert_success_envelope(live_response, status_code=200)
        assert live_payload["status"] == "alive"

        ready_response = client.get("/v1/health/ready")

        ready_payload = _assert_success_envelope(ready_response, status_code=200)
        assert ready_payload["status"] == "ok"
        assert ready_payload["checks"]["database"]["status"] == "ok"
        assert ready_payload["checks"]["kafka"]["status"] == "degraded"


def test_production_response_contracts(monkeypatch) -> None:
    session = SimpleNamespace()
    work_order = WorkOrderView(
        id="wo-1",
        work_order_no="WO-1001",
        order_id="order-1",
        process_step_key="cutting",
        assigned_user_id="user-1",
        rework_unread=False,
        status="pending",
        glass_type="Tempered",
        specification="6mm",
        quantity=3,
        completed_qty=0,
        defect_qty=0,
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(role="operator", stage="cutting")

    async def fake_list_work_orders(
        _session,
        *,
        limit: int,
        step_key: str | None,
        assignee_user_id: str | None,
        include_unassigned: bool,
    ):
        assert _session is session
        assert limit == 10
        assert step_key == "cutting"
        assert assignee_user_id == "user-1"
        assert include_unassigned is True
        return [work_order]

    async def fake_get_work_order(_session, *, work_order_id: str):
        assert _session is session
        if work_order_id == "missing-work-order":
            return None
        return work_order

    async def fake_list_schedule(
        _session,
        *,
        day,
        limit: int,
        step_key: str | None,
        assignee_user_id: str | None,
        include_unassigned: bool,
    ):
        assert _session is session
        assert str(day) == "2026-04-12"
        assert limit == 10
        assert step_key == "cutting"
        assert assignee_user_id == "user-1"
        assert include_unassigned is True
        return [work_order]

    monkeypatch.setattr(production_router.service, "list_work_orders", fake_list_work_orders)
    monkeypatch.setattr(production_router.service, "get_work_order", fake_get_work_order)
    monkeypatch.setattr(production_router.service, "list_schedule", fake_list_schedule)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/v1/production/work-orders",
                params={"limit": 10, "stage": "Cutting", "mine": True},
            )

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 1
            assert list_payload[0]["id"] == "wo-1"
            assert list_payload[0]["process_step_key"] == "cutting"

            detail_response = client.get("/v1/production/work-orders/wo-1")

            detail_payload = _assert_success_envelope(detail_response, status_code=200)
            assert detail_payload["id"] == "wo-1"
            assert detail_payload["work_order_no"] == "WO-1001"

            missing_response = client.get("/v1/production/work-orders/missing-work-order")

            missing_payload = _assert_error_envelope(
                missing_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Work order not found",
            )
            assert missing_payload["details"] == {}

            schedule_response = client.get(
                "/v1/production/schedule",
                params={"day": "2026-04-12", "limit": 10, "stage": "Cutting", "mine": True},
            )

            schedule_payload = _assert_success_envelope(schedule_response, status_code=200)
            assert len(schedule_payload) == 1
            assert schedule_payload[0]["assigned_user_id"] == "user-1"
    finally:
        app.dependency_overrides.clear()


def test_logistics_read_response_contracts(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    session = SimpleNamespace()
    shipment = ShipmentView(
        id="shipment-1",
        shipment_no="SHP-1001",
        order_id="order-1",
        status="shipped",
        carrier_name="Factory Fleet",
        tracking_no="TRACK-1001",
        vehicle_no="TRK-01",
        driver_name="Bob Driver",
        driver_phone="+86-13900000099",
        shipped_at=now,
        delivered_at=None,
        receiver_name=None,
        receiver_phone=None,
        signature_image=None,
        created_at=now,
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read"])

    async def fake_list_shipments(_session, *, limit: int, status: str | None, order_id: str | None):
        assert _session is session
        assert limit == 10
        assert status == "shipped"
        assert order_id == "order-1"
        return [shipment]

    async def fake_get_tracking(_session, *, tracking_no: str):
        assert _session is session
        assert tracking_no == "TRACK-1001"
        return shipment

    monkeypatch.setattr(logistics_router.service, "list_shipments", fake_list_shipments)
    monkeypatch.setattr(logistics_router.service, "get_tracking", fake_get_tracking)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get(
                "/v1/logistics/shipments",
                params={"limit": 10, "status": "shipped", "order_id": "order-1"},
            )

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 1
            assert list_payload[0]["id"] == "shipment-1"
            assert list_payload[0]["tracking_no"] == "TRACK-1001"

            detail_response = client.get("/v1/logistics/tracking/TRACK-1001")

            detail_payload = _assert_success_envelope(detail_response, status_code=200)
            assert detail_payload["shipment_no"] == "SHP-1001"
            assert detail_payload["status"] == "shipped"
            assert detail_payload["driver_name"] == "Bob Driver"
    finally:
        app.dependency_overrides.clear()


def test_finance_read_response_contracts(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    session = SimpleNamespace()
    receivable = ReceivableView(
        id="recv-1",
        order_id="order-1",
        customer_id="cust-1",
        amount=Decimal("450.50"),
        paid_amount=Decimal("100.00"),
        status="partial",
        due_date=date(2026, 4, 30),
        created_at=now,
        updated_at=now,
    )
    statement = StatementView(
        id="stmt-1",
        customer_id="cust-1",
        order_id="order-1",
        amount=Decimal("450.50"),
        paid_amount=Decimal("100.00"),
        status="partial",
        due_date=date(2026, 4, 30),
        created_at=now,
    )
    invoice = InvoiceView(
        id="inv-1",
        invoice_no="INV-1001",
        customer_id="cust-1",
        order_id="order-1",
        amount=Decimal("450.50"),
        paid_amount=Decimal("100.00"),
        status="partial",
        due_date=date(2026, 4, 30),
        created_at=now,
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(scopes=["orders:read", "finance:read"])

    async def fake_list_receivables(_session, *, limit: int, status: str | None, customer_id: str | None):
        assert _session is session
        assert limit == 10
        assert status == "partial"
        assert customer_id == "cust-1"
        return [receivable]

    async def fake_list_statements(_session, *, limit: int, customer_id: str | None):
        assert _session is session
        assert limit == 10
        assert customer_id == "cust-1"
        return [statement]

    async def fake_list_invoices(_session, *, limit: int, status: str | None, customer_id: str | None):
        assert _session is session
        assert limit == 10
        assert status == "partial"
        assert customer_id == "cust-1"
        return [invoice]

    monkeypatch.setattr(finance_router.service, "list_receivables", fake_list_receivables)
    monkeypatch.setattr(finance_router.service, "list_statements", fake_list_statements)
    monkeypatch.setattr(finance_router.service, "list_invoices", fake_list_invoices)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            receivables_response = client.get(
                "/v1/finance/receivables",
                params={"limit": 10, "status": "partial", "customer_id": "cust-1"},
            )

            receivables_payload = _assert_success_envelope(receivables_response, status_code=200)
            assert len(receivables_payload) == 1
            assert receivables_payload[0]["id"] == "recv-1"
            assert Decimal(receivables_payload[0]["amount"]) == Decimal("450.50")

            statements_response = client.get(
                "/v1/finance/statements",
                params={"limit": 10, "customer_id": "cust-1"},
            )

            statements_payload = _assert_success_envelope(statements_response, status_code=200)
            assert len(statements_payload) == 1
            assert statements_payload[0]["id"] == "stmt-1"
            assert statements_payload[0]["status"] == "partial"

            invoices_response = client.get(
                "/v1/finance/invoices",
                params={"limit": 10, "status": "partial", "customer_id": "cust-1"},
            )

            invoices_payload = _assert_success_envelope(invoices_response, status_code=200)
            assert len(invoices_payload) == 1
            assert invoices_payload[0]["invoice_no"] == "INV-1001"
            assert Decimal(invoices_payload[0]["paid_amount"]) == Decimal("100.00")
    finally:
        app.dependency_overrides.clear()


def test_customer_app_orders_create_response_contract_and_duplicate_error(monkeypatch) -> None:
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
                "specialInstructions": "Customer app contract order",
            }
            idempotency_key = f"contract-app-create-{uuid4()}"

            success_response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": idempotency_key},
                data=payload,
                files={},
            )

            success_payload = _assert_success_envelope(success_response, status_code=200)
            order_payload = success_payload["order"]
            assert order_payload["status"] == "pending"
            assert order_payload["totalQuantity"] == 3
            assert len(order_payload["items"]) == 1

            duplicate_response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": idempotency_key},
                data=payload,
                files={},
            )

            duplicate_payload = _assert_error_envelope(
                duplicate_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Duplicate write request.",
            )
            assert duplicate_payload["details"]["namespace"] == "app:orders:create"
            assert duplicate_payload["details"]["idempotency_key"] == idempotency_key
    finally:
        app.dependency_overrides.clear()


def test_customer_app_orders_viewer_forbidden_and_missing_idempotency(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    _patch_customer_app(monkeypatch, harness)
    current_user = {
        "value": make_auth_user(
            role="customer_viewer",
            scopes=["orders:read", "finance:read"],
            customer_id=harness.customer.id,
        )
    }

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            forbidden_response = client.post(
                "/v1/app/orders",
                headers={"Idempotency-Key": f"contract-app-viewer-{uuid4()}"},
                data={
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Customer app contract order",
                },
                files={},
            )

            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="Role is not allowed for this endpoint.",
            )
            assert forbidden_payload["details"]["actual_role"] == "customer_viewer"
            assert forbidden_payload["details"]["required_roles"] == ["customer"]

            current_user["value"] = make_auth_user(
                role="customer",
                scopes=["orders:read", "orders:write", "finance:read"],
                customer_id=harness.customer.id,
            )
            missing_key_response = client.post(
                "/v1/app/orders",
                data={
                    "glassType": "Tempered",
                    "thickness": "6mm",
                    "quantity": "3",
                    "priority": "normal",
                    "estimatedCompletionDate": "2026-04-12",
                    "specialInstructions": "Customer app contract order",
                },
                files={},
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "app:orders:create"
    finally:
        app.dependency_overrides.clear()


def test_customers_response_contract_for_list_profile_credit_and_create(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user(role="customer", customer_id=harness.customer.id)

    async def fake_get_redis():
        return harness.redis

    async def fake_list_customers(_session, limit: int = 100):
        assert _session is harness.session
        assert limit == 100
        return [_make_customer_profile(harness)]

    async def fake_get_customer_profile(_session, customer_id: str):
        assert customer_id == harness.customer.id
        return _make_customer_profile(harness)

    async def fake_get_credit_balance(_session, customer_id: str):
        assert customer_id == harness.customer.id
        return _make_customer_credit(harness)

    async def fake_create_customer(_session, payload):
        assert payload.company_name == "Contract Customer"
        return _make_customer_profile(harness)

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(customers_router.service, "list_customers", fake_list_customers)
    monkeypatch.setattr(customers_router.service, "get_customer_profile", fake_get_customer_profile)
    monkeypatch.setattr(customers_router.service, "get_credit_balance", fake_get_credit_balance)
    monkeypatch.setattr(customers_router.service, "create_customer", fake_create_customer)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get("/v1/customers")
            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 1
            assert list_payload[0]["id"] == harness.customer.id
            assert list_payload[0]["company_name"] == harness.customer.company_name

            profile_response = client.get("/v1/customers/profile")
            profile_payload = _assert_success_envelope(profile_response, status_code=200)
            assert profile_payload["id"] == harness.customer.id
            assert profile_payload["company_name"] == harness.customer.company_name

            credit_response = client.get("/v1/customers/credit")
            credit_payload = _assert_success_envelope(credit_response, status_code=200)
            assert credit_payload["customer_id"] == harness.customer.id
            assert Decimal(credit_payload["available_credit"]) == Decimal("100000.00")

            missing_key_response = client.post(
                "/v1/customers",
                json={"company_name": "Contract Customer"},
            )
            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "customers:create"

            create_response = client.post(
                "/v1/customers",
                headers={"Idempotency-Key": f"contract-customers-create-{uuid4()}"},
                json={"company_name": "Contract Customer"},
            )
            create_payload = _assert_success_envelope(create_response, status_code=201)
            assert create_payload["id"] == harness.customer.id
            assert create_payload["company_name"] == harness.customer.company_name
    finally:
        app.dependency_overrides.clear()


def test_notifications_response_contract_for_list_and_mark_read(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    notification = _make_notification("user-1")

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    async def fake_list_notifications(_session, user_id: str, limit: int = 100, unread_only: bool = False):
        assert user_id == "user-1"
        _ = (limit, unread_only)
        return [notification]

    async def fake_mark_notifications_read(_session, user_id: str, notification_ids=None):
        assert user_id == "user-1"
        assert notification_ids == [notification.id]
        return MarkNotificationsReadResult(updated_count=1)

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(notifications_router.service, "list_notifications", fake_list_notifications)
    monkeypatch.setattr(notifications_router.service, "mark_notifications_read", fake_mark_notifications_read)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get("/v1/notifications")
            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload) == 1
            assert list_payload[0]["id"] == notification.id
            assert list_payload[0]["is_read"] is False

            missing_key_response = client.put(
                "/v1/notifications/read",
                json={"notification_ids": [notification.id]},
            )
            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "notifications:mark-read"

            mark_read_response = client.put(
                "/v1/notifications/read",
                headers={"Idempotency-Key": f"contract-notifications-read-{uuid4()}"},
                json={"notification_ids": [notification.id]},
            )
            mark_read_payload = _assert_success_envelope(mark_read_response, status_code=200)
            assert mark_read_payload["updated_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_workspace_customers_response_contract(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    session = SimpleNamespace()

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user()

    async def fake_serialize_customers(_session):
        assert _session is session
        return [
            {
                "id": "cust-1",
                "companyName": "Integration Customer",
                "contactName": "Alice",
                "phone": "13800000000",
                "email": "alice@example.com",
                "notes": "Factory pickup",
                "totalOrders": 2,
                "activeOrders": 1,
                "hasActiveOrders": True,
                "lastOrderAt": now,
                "createdAt": now,
                "updatedAt": now,
            }
        ]

    monkeypatch.setattr(workspace_router.workspace_ui, "serialize_customers", fake_serialize_customers)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/workspace/customers")

            payload = _assert_success_envelope(response, status_code=200)
            assert len(payload["customers"]) == 1
            assert payload["customers"][0]["id"] == "cust-1"
            assert payload["customers"][0]["companyName"] == "Integration Customer"
            assert payload["customers"][0]["totalOrders"] == 2
            assert payload["customers"][0]["hasActiveOrders"] is True
    finally:
        app.dependency_overrides.clear()


def test_workspace_customers_write_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    now = datetime.now(timezone.utc)
    current_user = {"value": make_auth_user(stage="cutting")}
    serialized_rows = {
        "value": [
            {
                "id": "cust-1",
                "companyName": "Integration Customer",
                "contactName": "Alice",
                "phone": "13800000000",
                "email": "alice@example.com",
                "notes": "Factory pickup",
                "totalOrders": 0,
                "activeOrders": 0,
                "hasActiveOrders": False,
                "lastOrderAt": None,
                "createdAt": now,
                "updatedAt": now,
            }
        ]
    }

    created_customer = SimpleNamespace(
        id="cust-2",
        company_name="Contract Workspace Customer",
        contact_name="Bob",
        phone="13800000001",
        email="bob@example.com",
        address="Workshop 2",
        created_at=now,
        updated_at=now,
    )
    updated_customer = SimpleNamespace(
        id="cust-2",
        company_name="Updated Workspace Customer",
        contact_name="Bob",
        phone="13800000002",
        email="updated@example.com",
        address="Workshop 3",
        created_at=now,
        updated_at=now,
    )

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_create_workspace_customer(
        _session,
        *,
        company_name: str,
        contact_name: str | None,
        phone: str | None,
        email: str | None,
        address: str | None,
    ):
        assert _session is harness.session
        assert company_name == "Contract Workspace Customer"
        assert contact_name == "Bob"
        assert phone == "13800000001"
        assert email == "bob@example.com"
        assert address == "Workshop 2"
        serialized_rows["value"] = [
            {
                "id": "cust-2",
                "companyName": "Contract Workspace Customer",
                "contactName": "Bob",
                "phone": "13800000001",
                "email": "bob@example.com",
                "notes": "Workshop 2",
                "totalOrders": 0,
                "activeOrders": 0,
                "hasActiveOrders": False,
                "lastOrderAt": None,
                "createdAt": now,
                "updatedAt": now,
            }
        ]
        return created_customer

    async def fake_update_customer(_session, customer_id: str, payload):
        assert _session is harness.session
        assert customer_id == "cust-2"
        assert payload.company_name == "Updated Workspace Customer"
        assert payload.phone == "13800000002"
        assert payload.email == "updated@example.com"
        assert payload.address == "Workshop 3"
        serialized_rows["value"] = [
            {
                "id": "cust-2",
                "companyName": "Updated Workspace Customer",
                "contactName": "Bob",
                "phone": "13800000002",
                "email": "updated@example.com",
                "notes": "Workshop 3",
                "totalOrders": 0,
                "activeOrders": 0,
                "hasActiveOrders": False,
                "lastOrderAt": None,
                "createdAt": now,
                "updatedAt": now,
            }
        ]
        return updated_customer

    def fake_serialize_customer(customer, *, total_orders: int = 0, active_orders: int = 0, last_order_at=None):
        _ = (total_orders, active_orders, last_order_at)
        return {
            "id": customer.id,
            "companyName": customer.company_name,
            "contactName": customer.contact_name,
            "phone": customer.phone,
            "email": customer.email,
            "notes": customer.address,
            "totalOrders": 0,
            "activeOrders": 0,
            "hasActiveOrders": False,
            "lastOrderAt": None,
            "createdAt": customer.created_at,
            "updatedAt": customer.updated_at,
        }

    async def fake_serialize_customers(_session):
        assert _session is harness.session
        return serialized_rows["value"]

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(
        workspace_router.customers_service,
        "create_workspace_customer",
        fake_create_workspace_customer,
    )
    monkeypatch.setattr(workspace_router.customers_service, "update_customer", fake_update_customer)
    monkeypatch.setattr(workspace_router.workspace_ui, "serialize_customer", fake_serialize_customer)
    monkeypatch.setattr(workspace_router.workspace_ui, "serialize_customers", fake_serialize_customers)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            forbidden_response = client.post(
                "/v1/workspace/customers",
                headers={"Idempotency-Key": f"contract-workspace-customers-forbidden-{uuid4()}"},
                json={"companyName": "Contract Workspace Customer"},
            )
            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_payload["details"] == {}

            current_user["value"] = make_auth_user()

            missing_key_create_response = client.post(
                "/v1/workspace/customers",
                json={
                    "companyName": "Contract Workspace Customer",
                    "contactName": "Bob",
                    "phone": "13800000001",
                    "email": "bob@example.com",
                    "notes": "Workshop 2",
                },
            )
            missing_key_create_payload = _assert_error_envelope(
                missing_key_create_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_create_payload["details"]["namespace"] == "workspace:customers:create"

            create_response = client.post(
                "/v1/workspace/customers",
                headers={"Idempotency-Key": f"contract-workspace-customers-create-{uuid4()}"},
                json={
                    "companyName": "Contract Workspace Customer",
                    "contactName": "Bob",
                    "phone": "13800000001",
                    "email": "bob@example.com",
                    "notes": "Workshop 2",
                },
            )
            create_payload = _assert_success_envelope(create_response, status_code=200)
            assert create_payload["customer"]["id"] == "cust-2"
            assert create_payload["customer"]["companyName"] == "Contract Workspace Customer"
            assert create_payload["customers"][0]["id"] == "cust-2"

            missing_key_update_response = client.patch(
                "/v1/workspace/customers/cust-2",
                json={
                    "companyName": "Updated Workspace Customer",
                    "phone": "13800000002",
                    "email": "updated@example.com",
                    "notes": "Workshop 3",
                },
            )
            missing_key_update_payload = _assert_error_envelope(
                missing_key_update_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_update_payload["details"]["namespace"] == "workspace:customers:update"

            update_response = client.patch(
                "/v1/workspace/customers/cust-2",
                headers={"Idempotency-Key": f"contract-workspace-customers-update-{uuid4()}"},
                json={
                    "companyName": "Updated Workspace Customer",
                    "phone": "13800000002",
                    "email": "updated@example.com",
                    "notes": "Workshop 3",
                },
            )
            update_payload = _assert_success_envelope(update_response, status_code=200)
            assert update_payload["customer"]["id"] == "cust-2"
            assert update_payload["customer"]["companyName"] == "Updated Workspace Customer"
            assert update_payload["customers"][0]["phone"] == "13800000002"
    finally:
        app.dependency_overrides.clear()


def test_workspace_notifications_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return make_auth_user()

    async def fake_get_redis():
        return harness.redis

    async def fake_serialize_notifications(_session, user_id: str):
        assert user_id == "user-1"
        return [{"id": "notif-1", "title": "Workspace notice", "isRead": False}]

    async def fake_mark_notifications_read(_session, user_id: str, notification_ids=None):
        assert user_id == "user-1"
        assert notification_ids is None
        return MarkNotificationsReadResult(updated_count=1)

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(workspace_router.workspace_ui, "serialize_notifications", fake_serialize_notifications)
    monkeypatch.setattr(workspace_router.notifications_service, "mark_notifications_read", fake_mark_notifications_read)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get("/v1/workspace/notifications")
            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert list_payload["notifications"][0]["id"] == "notif-1"

            missing_key_response = client.post("/v1/workspace/notifications/read")
            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:notifications:mark-read"

            mark_read_response = client.post(
                "/v1/workspace/notifications/read",
                headers={"Idempotency-Key": f"contract-workspace-notifications-{uuid4()}"},
            )
            mark_read_payload = _assert_success_envelope(mark_read_response, status_code=200)
            assert mark_read_payload["notifications"][0]["id"] == "notif-1"
    finally:
        app.dependency_overrides.clear()


def test_workspace_shipments_and_receivables_read_response_contract(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    session = SimpleNamespace()
    shipment = ShipmentView(
        id="shipment-1",
        shipment_no="SHP-2001",
        order_id="order-1",
        status="shipped",
        carrier_name="Factory Fleet",
        tracking_no="TRACK-2001",
        vehicle_no="TRK-02",
        driver_name="Alice Driver",
        driver_phone="+86-13900000100",
        shipped_at=now,
        delivered_at=None,
        receiver_name=None,
        receiver_phone=None,
        signature_image=None,
        created_at=now,
    ).model_dump(mode="json")
    receivable = ReceivableView(
        id="recv-2",
        order_id="order-1",
        customer_id="cust-1",
        amount=Decimal("520.00"),
        paid_amount=Decimal("120.00"),
        status="partial",
        due_date=date(2026, 5, 5),
        created_at=now,
        updated_at=now,
    ).model_dump(mode="json")

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return make_auth_user(role="manager", scopes=["orders:read", "orders:write", "finance:read"])

    async def fake_list_workspace_shipments(_session, *, limit: int, status: str | None, order_id: str | None):
        assert _session is session
        assert limit == 10
        assert status == "shipped"
        assert order_id == "order-1"
        return [shipment]

    async def fake_list_workspace_receivables(_session, *, limit: int, status: str | None, customer_id: str | None):
        assert _session is session
        assert limit == 10
        assert status == "partial"
        assert customer_id == "cust-1"
        return [receivable]

    monkeypatch.setattr(workspace_router.workspace_logistics, "list_workspace_shipments", fake_list_workspace_shipments)
    monkeypatch.setattr(workspace_router.workspace_finance, "list_workspace_receivables", fake_list_workspace_receivables)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            shipments_response = client.get(
                "/v1/workspace/shipments",
                params={"limit": 10, "status": "shipped", "order_id": "order-1"},
            )

            shipments_payload = _assert_success_envelope(shipments_response, status_code=200)
            assert shipments_payload["shipments"][0]["shipment_no"] == "SHP-2001"
            assert shipments_payload["shipments"][0]["tracking_no"] == "TRACK-2001"

            receivables_response = client.get(
                "/v1/workspace/receivables",
                params={"limit": 10, "status": "partial", "customer_id": "cust-1"},
            )

            receivables_payload = _assert_success_envelope(receivables_response, status_code=200)
            assert receivables_payload["receivables"][0]["id"] == "recv-2"
            assert Decimal(receivables_payload["receivables"][0]["amount"]) == Decimal("520.00")
            assert receivables_payload["receivables"][0]["status"] == "partial"
    finally:
        app.dependency_overrides.clear()


def test_workspace_settings_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    glass_type_row = SimpleNamespace(
        id="glass-1",
        name="Ultra Clear",
        is_active=True,
        sort_order=0,
        updated_at=datetime.now(timezone.utc),
    )
    glass_type_state = {
        "value": {"id": "glass-1", "name": "Ultra Clear", "isActive": True}
    }
    template_payload = {
        "templateKey": "ready_for_pickup",
        "name": "Ready for Pickup 邮件",
        "subjectTemplate": "订单 {{orderNo}} 已可取货",
        "bodyTemplate": "您好 {{customerName}}，订单 {{orderNo}} 已可取货。",
        "availableVariables": ["customerName", "orderNo", "glassType", "specification", "quantity"],
        "updatedAt": datetime.now(timezone.utc),
        "updatedByName": "Customer Demo",
    }
    email_log_payload = {
        "id": "email-1",
        "orderId": "order-1",
        "orderNo": "ORD-1001",
        "customerEmail": "alice@example.com",
        "subject": "Pickup ready",
        "body": "Body preview",
        "status": "sent",
        "transport": "smtp",
        "errorMessage": "",
        "providerMessageId": "provider-1",
        "createdAt": datetime.now(timezone.utc),
        "sentAt": datetime.now(timezone.utc),
    }
    current_user = {"value": make_auth_user(stage="cutting")}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    async def fake_list_glass_types(_session, actor_user_id: str | None = None):
        _ = actor_user_id
        return [glass_type_state["value"]]

    async def fake_create_glass_type(_session, *, name: str, actor_user_id: str):
        assert name == "Ultra Clear"
        assert actor_user_id == "user-1"
        glass_type_state["value"] = {"id": "glass-1", "name": "Ultra Clear", "isActive": True}
        return glass_type_row

    async def fake_update_glass_type(
        _session,
        glass_type_id: str,
        *,
        name: str | None = None,
        is_active: bool | None = None,
        actor_user_id: str,
    ):
        assert _session is harness.session
        assert glass_type_id == "glass-1"
        assert name == "Low-E"
        assert is_active is False
        assert actor_user_id == "user-1"
        glass_type_state["value"] = {"id": "glass-1", "name": "Low-E", "isActive": False}
        return SimpleNamespace(
            id="glass-1",
            name="Low-E",
            is_active=False,
            sort_order=0,
            updated_at=datetime.now(timezone.utc),
        )

    async def fake_get_notification_template(_session, template_key: str, actor_user_id: str):
        assert _session is harness.session
        assert actor_user_id == "user-1"
        if template_key != "ready_for_pickup":
            raise AppError(code="VALIDATION_ERROR", message="模板不存在。", status_code=404)
        return template_payload

    async def fake_update_notification_template(
        _session,
        template_key: str,
        *,
        subject_template: str,
        body_template: str,
        actor_user_id: str,
    ):
        assert _session is harness.session
        assert template_key == "ready_for_pickup"
        assert subject_template == "已可取货：{{orderNo}}"
        assert body_template == "请安排到厂取货。"
        assert actor_user_id == "user-1"
        return {
            "templateKey": "ready_for_pickup",
            "name": "Ready for Pickup 邮件",
            "subjectTemplate": subject_template,
            "bodyTemplate": body_template,
            "availableVariables": [
                "customerName",
                "orderNo",
                "glassType",
                "specification",
                "quantity",
            ],
            "updatedAt": datetime.now(timezone.utc),
            "updatedByName": "Customer Demo",
        }

    async def fake_list_email_logs(_session, limit: int = 20):
        assert _session is harness.session
        assert limit == 5
        return [email_log_payload]

    def fake_serialize_glass_type(row):
        return {"id": row.id, "name": row.name, "isActive": bool(row.is_active)}

    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    monkeypatch.setattr(workspace_router.workspace_settings, "list_glass_types", fake_list_glass_types)
    monkeypatch.setattr(workspace_router.workspace_settings, "create_glass_type", fake_create_glass_type)
    monkeypatch.setattr(workspace_router.workspace_settings, "update_glass_type", fake_update_glass_type)
    monkeypatch.setattr(
        workspace_router.workspace_settings,
        "get_notification_template",
        fake_get_notification_template,
    )
    monkeypatch.setattr(
        workspace_router.workspace_settings,
        "update_notification_template",
        fake_update_notification_template,
    )
    monkeypatch.setattr(workspace_router.workspace_settings, "list_email_logs", fake_list_email_logs)
    monkeypatch.setattr(workspace_router.workspace_settings, "serialize_glass_type", fake_serialize_glass_type)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            forbidden_response = client.get("/v1/workspace/settings/glass-types")
            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权访问玻璃类型配置。",
            )
            assert forbidden_payload["details"] == {}

            current_user["value"] = make_auth_user()
            list_response = client.get("/v1/workspace/settings/glass-types")
            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert list_payload["glassTypes"][0]["name"] == "Ultra Clear"

            template_response = client.get(
                "/v1/workspace/settings/notification-templates/ready_for_pickup"
            )
            template_response_payload = _assert_success_envelope(template_response, status_code=200)
            assert template_response_payload["template"]["templateKey"] == "ready_for_pickup"
            assert template_response_payload["template"]["updatedByName"] == "Customer Demo"

            missing_template_response = client.get(
                "/v1/workspace/settings/notification-templates/missing-template"
            )
            missing_template_payload = _assert_error_envelope(
                missing_template_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="模板不存在。",
            )
            assert missing_template_payload["details"] == {}

            email_logs_response = client.get("/v1/workspace/email-logs", params={"limit": 5})
            email_logs_payload = _assert_success_envelope(email_logs_response, status_code=200)
            assert email_logs_payload["logs"][0]["id"] == "email-1"
            assert email_logs_payload["logs"][0]["orderNo"] == "ORD-1001"
            assert email_logs_payload["logs"][0]["status"] == "sent"

            missing_key_update_glass_type_response = client.patch(
                "/v1/workspace/settings/glass-types/glass-1",
                json={"name": "Low-E", "isActive": False},
            )
            missing_key_update_glass_type_payload = _assert_error_envelope(
                missing_key_update_glass_type_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert (
                missing_key_update_glass_type_payload["details"]["namespace"]
                == "workspace:settings:glass-types:update"
            )

            update_glass_type_response = client.patch(
                "/v1/workspace/settings/glass-types/glass-1",
                headers={"Idempotency-Key": f"contract-glass-type-update-{uuid4()}"},
                json={"name": "Low-E", "isActive": False},
            )
            update_glass_type_payload = _assert_success_envelope(update_glass_type_response, status_code=200)
            assert update_glass_type_payload["glassType"]["name"] == "Low-E"
            assert update_glass_type_payload["glassType"]["isActive"] is False
            assert update_glass_type_payload["glassTypes"][0]["name"] == "Low-E"

            missing_key_update_template_response = client.put(
                "/v1/workspace/settings/notification-templates/ready_for_pickup",
                json={
                    "subjectTemplate": "已可取货：{{orderNo}}",
                    "bodyTemplate": "请安排到厂取货。",
                },
            )
            missing_key_update_template_payload = _assert_error_envelope(
                missing_key_update_template_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert (
                missing_key_update_template_payload["details"]["namespace"]
                == "workspace:settings:notification-template:update"
            )

            update_template_response = client.put(
                "/v1/workspace/settings/notification-templates/ready_for_pickup",
                headers={"Idempotency-Key": f"contract-notification-template-update-{uuid4()}"},
                json={
                    "subjectTemplate": "已可取货：{{orderNo}}",
                    "bodyTemplate": "请安排到厂取货。",
                },
            )
            update_template_payload = _assert_success_envelope(update_template_response, status_code=200)
            assert update_template_payload["template"]["subjectTemplate"] == "已可取货：{{orderNo}}"
            assert update_template_payload["template"]["bodyTemplate"] == "请安排到厂取货。"

            missing_key_response = client.post(
                "/v1/workspace/settings/glass-types",
                json={"name": "Ultra Clear"},
            )
            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:settings:glass-types:create"

            create_response = client.post(
                "/v1/workspace/settings/glass-types",
                headers={"Idempotency-Key": f"contract-glass-type-create-{uuid4()}"},
                json={"name": "Ultra Clear"},
            )
            create_payload = _assert_success_envelope(create_response, status_code=200)
            assert create_payload["glassType"]["name"] == "Ultra Clear"
            assert create_payload["glassTypes"][0]["id"] == "glass-1"
    finally:
        app.dependency_overrides.clear()


def test_logistics_write_response_contract(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            pending_order_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": f"contract-pending-order-{uuid4()}"},
                json={
                    "customer_id": harness.customer.id,
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "Pending shipment contract order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 1,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )
            pending_order_id = _assert_success_envelope(pending_order_response, status_code=201)["id"]

            current_user["value"] = make_auth_user(scopes=["orders:read", "logistics:write"])
            invalid_status_response = client.post(
                "/v1/logistics/shipments",
                headers={"Idempotency-Key": f"contract-shipment-pending-{uuid4()}"},
                json={"order_id": pending_order_id, "tracking_no": "TRACK-PENDING-1"},
            )

            invalid_status_payload = _assert_error_envelope(
                invalid_status_response,
                status_code=409,
                code="ORDER_INVALID_TRANSITION",
                message="Order is not ready for shipment.",
            )
            assert invalid_status_payload["details"]["order_id"] == pending_order_id

            current_user["value"] = make_auth_user(scopes=["orders:read", "orders:write"])
            order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(scopes=["orders:read"])
            forbidden_response = client.post(
                "/v1/logistics/shipments",
                headers={"Idempotency-Key": f"contract-shipment-forbidden-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "tracking_no": "TRACK-CONTRACT-1",
                },
            )

            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="Missing required permissions.",
            )
            assert forbidden_payload["details"]["missing_scopes"] == ["logistics:write"]

            current_user["value"] = make_auth_user(scopes=["orders:read", "logistics:write"])
            missing_key_response = client.post(
                "/v1/logistics/shipments",
                json={
                    "order_id": order_id,
                    "tracking_no": "TRACK-CONTRACT-1",
                },
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "logistics:shipments:create"

            success_response = client.post(
                "/v1/logistics/shipments",
                headers={"Idempotency-Key": f"contract-shipment-create-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "carrier_name": "Factory Fleet",
                    "tracking_no": "TRACK-CONTRACT-1",
                    "vehicle_no": "TRK-99",
                    "driver_name": "Bob Driver",
                    "driver_phone": "+86-13900000099",
                    "shipped_at": "2026-04-12T10:00:00Z",
                },
            )

            success_payload = _assert_success_envelope(success_response, status_code=201)
            assert success_payload["order_id"] == order_id
            assert success_payload["status"] == "shipped"
            assert success_payload["tracking_no"] == "TRACK-CONTRACT-1"
            assert success_payload["driver_name"] == "Bob Driver"
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_finance_payment_response_contract_and_partial_settlement(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            pending_order_response = client.post(
                "/v1/orders",
                headers={"Idempotency-Key": f"contract-pending-billing-order-{uuid4()}"},
                json={
                    "customer_id": harness.customer.id,
                    "delivery_address": "Factory pickup",
                    "expected_delivery_date": "2026-04-12T10:00:00Z",
                    "priority": "normal",
                    "remark": "Pending settlement contract order",
                    "items": [
                        {
                            "product_id": "product-1",
                            "product_name": "Tempered Glass Panel",
                            "glass_type": "Tempered",
                            "specification": "6mm",
                            "width_mm": 1200,
                            "height_mm": 800,
                            "quantity": 1,
                            "unit_price": "88.00",
                            "process_requirements": "temper",
                        }
                    ],
                },
            )
            pending_order_id = _assert_success_envelope(pending_order_response, status_code=201)["id"]

            current_user["value"] = make_auth_user(scopes=["orders:read", "finance:write"])
            invalid_status_response = client.post(
                "/v1/finance/receivables",
                headers={"Idempotency-Key": f"contract-receivable-pending-{uuid4()}"},
                json={
                    "order_id": pending_order_id,
                    "due_date": "2026-04-30",
                    "amount": "88.00",
                    "invoice_no": "INV-PENDING-1",
                },
            )

            invalid_status_payload = _assert_error_envelope(
                invalid_status_response,
                status_code=409,
                code="ORDER_INVALID_TRANSITION",
                message="Order is not ready for settlement.",
            )
            assert invalid_status_payload["details"]["order_id"] == pending_order_id

            current_user["value"] = make_auth_user(scopes=["orders:read", "orders:write"])
            order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(scopes=["orders:read", "finance:write"])
            create_response = client.post(
                "/v1/finance/receivables",
                headers={"Idempotency-Key": f"contract-receivable-create-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "due_date": "2026-04-30",
                    "amount": "450.50",
                    "invoice_no": "INV-CONTRACT-1",
                },
            )

            create_payload = _assert_success_envelope(create_response, status_code=201)
            receivable_id = create_payload["id"]
            assert create_payload["status"] == "unpaid"
            assert Decimal(create_payload["amount"]) == Decimal("450.50")
            assert Decimal(create_payload["paid_amount"]) == Decimal("0.00")

            partial_payment_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": f"contract-receivable-partial-{uuid4()}"},
                json={"amount": "100.00"},
            )

            partial_payload = _assert_success_envelope(partial_payment_response, status_code=200)
            assert partial_payload["status"] == "partial"
            assert Decimal(partial_payload["paid_amount"]) == Decimal("100.00")

            lower_amount_response = client.post(
                "/v1/finance/receivables",
                headers={"Idempotency-Key": f"contract-receivable-lower-amount-{uuid4()}"},
                json={
                    "order_id": order_id,
                    "due_date": "2026-04-30",
                    "amount": "99.99",
                    "invoice_no": "INV-CONTRACT-LOWER",
                },
            )

            lower_amount_payload = _assert_error_envelope(
                lower_amount_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Receivable amount cannot be less than paid amount.",
            )
            assert lower_amount_payload["details"]["receivable_id"] == receivable_id

            overpay_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": f"contract-receivable-overpay-{uuid4()}"},
                json={"amount": "400.51"},
            )

            overpay_payload = _assert_error_envelope(
                overpay_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Payment exceeds receivable amount.",
            )
            assert overpay_payload["details"]["receivable_id"] == receivable_id

            final_payment_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": f"contract-receivable-final-{uuid4()}"},
                json={"amount": "350.50"},
            )

            final_payload = _assert_success_envelope(final_payment_response, status_code=200)
            assert final_payload["status"] == "paid"
            assert Decimal(final_payload["paid_amount"]) == Decimal("450.50")

            refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"contract-receivable-refund-{uuid4()}"},
                json={"amount": "50.50"},
            )

            refund_payload = _assert_success_envelope(refund_response, status_code=200)
            assert refund_payload["status"] == "partial"
            assert Decimal(refund_payload["paid_amount"]) == Decimal("400.00")

            over_refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"contract-receivable-over-refund-{uuid4()}"},
                json={"amount": "401.00"},
            )

            over_refund_payload = _assert_error_envelope(
                over_refund_response,
                status_code=409,
                code="VALIDATION_ERROR",
                message="Refund exceeds paid amount.",
            )
            assert over_refund_payload["details"]["receivable_id"] == receivable_id

            final_refund_response = client.post(
                f"/v1/finance/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"contract-receivable-final-refund-{uuid4()}"},
                json={"amount": "400.00"},
            )

            final_refund_payload = _assert_success_envelope(final_refund_response, status_code=200)
            assert final_refund_payload["status"] == "unpaid"
            assert Decimal(final_refund_payload["paid_amount"]) == Decimal("0.00")
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_finance_write_error_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(scopes=["orders:read", "finance:write"])
            missing_key_response = client.post(
                "/v1/finance/receivables",
                json={
                    "order_id": order_id,
                    "due_date": "2026-04-30",
                    "amount": "88.00",
                    "invoice_no": "INV-CONTRACT-MISSING-KEY",
                },
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "finance:receivables:create"

            missing_payment_response = client.post(
                "/v1/finance/receivables/missing-receivable/payments",
                headers={"Idempotency-Key": f"contract-receivable-missing-payment-{uuid4()}"},
                json={"amount": "10.00"},
            )

            missing_payment_payload = _assert_error_envelope(
                missing_payment_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Receivable not found.",
            )
            assert missing_payment_payload["details"]["receivable_id"] == "missing-receivable"

            missing_refund_response = client.post(
                "/v1/finance/receivables/missing-receivable/refunds",
                headers={"Idempotency-Key": f"contract-receivable-missing-refund-{uuid4()}"},
                json={"amount": "10.00"},
            )

            missing_refund_payload = _assert_error_envelope(
                missing_refund_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Receivable not found.",
            )
            assert missing_refund_payload["details"]["receivable_id"] == "missing-receivable"
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_workspace_logistics_and_finance_write_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(stage="cutting")
            forbidden_shipment_response = client.post(
                f"/v1/workspace/orders/{order_id}/shipment",
                headers={"Idempotency-Key": f"contract-workspace-shipment-forbidden-{uuid4()}"},
                json={"trackingNo": "TRACK-WORKSPACE-1"},
            )
            forbidden_shipment_payload = _assert_error_envelope(
                forbidden_shipment_response,
                status_code=403,
                code="FORBIDDEN",
                message="当前角色无权执行此操作。",
            )
            assert forbidden_shipment_payload["details"] == {}

            current_user["value"] = make_auth_user()

            missing_key_shipment_response = client.post(
                f"/v1/workspace/orders/{order_id}/shipment",
                json={"trackingNo": "TRACK-WORKSPACE-1"},
            )
            missing_key_shipment_payload = _assert_error_envelope(
                missing_key_shipment_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_shipment_payload["details"]["namespace"] == "workspace:shipments:create"

            shipment_create_response = client.post(
                f"/v1/workspace/orders/{order_id}/shipment",
                headers={"Idempotency-Key": f"contract-workspace-shipment-create-{uuid4()}"},
                json={
                    "carrierName": "Factory Fleet",
                    "trackingNo": "TRACK-WORKSPACE-1",
                    "vehicleNo": "TRK-88",
                    "driverName": "Bob Driver",
                    "driverPhone": "+86-13900000088",
                    "shippedAt": "2026-04-12T10:00:00Z",
                },
            )
            shipment_create_payload = _assert_success_envelope(shipment_create_response, status_code=200)
            shipment_id = shipment_create_payload["shipment"]["id"]
            assert shipment_create_payload["shipment"]["order_id"] == order_id
            assert shipment_create_payload["shipment"]["status"] == "shipped"
            assert shipment_create_payload["shipment"]["tracking_no"] == "TRACK-WORKSPACE-1"
            assert shipment_create_payload["shipment"]["driver_name"] == "Bob Driver"

            missing_key_deliver_response = client.post(
                f"/v1/workspace/shipments/{shipment_id}/deliver",
                json={"receiverName": "Carol Receiver"},
            )
            missing_key_deliver_payload = _assert_error_envelope(
                missing_key_deliver_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_deliver_payload["details"]["namespace"] == "workspace:shipments:deliver"

            shipment_deliver_response = client.post(
                f"/v1/workspace/shipments/{shipment_id}/deliver",
                headers={"Idempotency-Key": f"contract-workspace-shipment-deliver-{uuid4()}"},
                json={
                    "receiverName": "Carol Receiver",
                    "receiverPhone": "+86-13800000000",
                    "deliveredAt": "2026-04-12T14:30:00Z",
                },
            )
            shipment_deliver_payload = _assert_success_envelope(shipment_deliver_response, status_code=200)
            assert shipment_deliver_payload["shipment"]["id"] == shipment_id
            assert shipment_deliver_payload["shipment"]["status"] == "delivered"
            assert shipment_deliver_payload["shipment"]["receiver_name"] == "Carol Receiver"

            receivable_create_response = client.post(
                f"/v1/workspace/orders/{order_id}/receivable",
                headers={"Idempotency-Key": f"contract-workspace-receivable-create-{uuid4()}"},
                json={
                    "dueDate": "2026-04-30",
                    "amount": "450.50",
                    "invoiceNo": "INV-WORKSPACE-1",
                },
            )
            receivable_create_payload = _assert_success_envelope(receivable_create_response, status_code=200)
            receivable_id = receivable_create_payload["receivable"]["id"]
            assert receivable_create_payload["receivable"]["order_id"] == order_id
            assert receivable_create_payload["receivable"]["status"] == "unpaid"
            assert Decimal(receivable_create_payload["receivable"]["amount"]) == Decimal("450.50")
            assert receivable_create_payload["receivable"]["due_date"] == "2026-04-30"

            payment_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/payments",
                headers={"Idempotency-Key": f"contract-workspace-receivable-payment-{uuid4()}"},
                json={"amount": "450.50"},
            )
            payment_payload = _assert_success_envelope(payment_response, status_code=200)
            assert payment_payload["receivable"]["id"] == receivable_id
            assert payment_payload["receivable"]["status"] == "paid"
            assert Decimal(payment_payload["receivable"]["paid_amount"]) == Decimal("450.50")

            refund_response = client.post(
                f"/v1/workspace/receivables/{receivable_id}/refunds",
                headers={"Idempotency-Key": f"contract-workspace-receivable-refund-{uuid4()}"},
                json={"amount": "50.50"},
            )
            refund_payload = _assert_success_envelope(refund_response, status_code=200)
            assert refund_payload["receivable"]["id"] == receivable_id
            assert refund_payload["receivable"]["status"] == "partial"
            assert Decimal(refund_payload["receivable"]["paid_amount"]) == Decimal("400.00")
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()


def test_workspace_receivable_write_error_response_contracts(monkeypatch) -> None:
    harness = build_order_inventory_harness(available_qty=10)
    original_service = orders_router.service
    current_user = {"value": make_auth_user(scopes=["orders:read", "orders:write"])}

    async def override_session() -> AsyncGenerator:
        yield harness.session

    async def override_current_user():
        return current_user["value"]

    async def fake_get_redis():
        return harness.redis

    monkeypatch.setattr(orders_router, "service", harness.orders_service)
    monkeypatch.setattr("infra.security.idempotency.get_redis", fake_get_redis)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            order_id = _drive_order_to_ready_for_pickup(client, current_user, harness.customer.id)

            current_user["value"] = make_auth_user(role="operator")
            missing_key_response = client.post(
                f"/v1/workspace/orders/{order_id}/receivable",
                json={
                    "dueDate": "2026-04-30",
                    "amount": "88.00",
                    "invoiceNo": "INV-WORKSPACE-MISSING-KEY",
                },
            )

            missing_key_payload = _assert_error_envelope(
                missing_key_response,
                status_code=400,
                code="VALIDATION_ERROR",
                message="Idempotency-Key header is required for write operations.",
            )
            assert missing_key_payload["details"]["namespace"] == "workspace:receivables:create"

            missing_payment_response = client.post(
                "/v1/workspace/receivables/missing-receivable/payments",
                headers={"Idempotency-Key": f"contract-workspace-receivable-missing-payment-{uuid4()}"},
                json={"amount": "10.00"},
            )

            _assert_error_envelope(
                missing_payment_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Receivable not found.",
            )

            missing_refund_response = client.post(
                "/v1/workspace/receivables/missing-receivable/refunds",
                headers={"Idempotency-Key": f"contract-workspace-receivable-missing-refund-{uuid4()}"},
                json={"amount": "10.00"},
            )

            _assert_error_envelope(
                missing_refund_response,
                status_code=404,
                code="VALIDATION_ERROR",
                message="Receivable not found.",
            )
    finally:
        orders_router.service = original_service
        app.dependency_overrides.clear()