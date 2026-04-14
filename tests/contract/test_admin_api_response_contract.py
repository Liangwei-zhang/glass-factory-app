from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.admin_api.main import app
from apps.admin_api.routers import health as admin_health_router
from apps.admin_api.routers import runtime as runtime_router
from infra.db.models.customers import CustomerModel
from infra.db.models.production import ProductionLineModel
from infra.db.models.users import UserModel
from infra.db.session import get_db_session
from infra.security.auth import AuthUser, get_current_user


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _RowCountResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _ScalarRowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeUsersSession:
    def __init__(self, *, execute_results=None, scalar_results=None, get_map=None):
        self._execute_results = list(execute_results or [])
        self._scalar_results = list(scalar_results or [])
        self._get_map = dict(get_map or {})
        self.commit_calls = 0

    async def execute(self, _statement):
        if not self._execute_results:
            raise AssertionError("Unexpected execute call in admin users contract test.")
        return self._execute_results.pop(0)

    async def scalar(self, _statement):
        if not self._scalar_results:
            raise AssertionError("Unexpected scalar call in admin users contract test.")
        return self._scalar_results.pop(0)

    async def get(self, model, obj_id: str):
        return self._get_map.get((model, obj_id))

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_calls += 1


def _make_auth_user(*, role: str) -> AuthUser:
    return AuthUser(
        sub="admin-user-1",
        role=role,
        scopes=[],
        stage=None,
        sid="session-1",
    )


def _assert_success_envelope(response, *, status_code: int) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert "data" in payload
    assert "request_id" in payload
    assert "timestamp" in payload
    assert response.headers["X-Request-ID"] == payload["request_id"]
    return payload["data"]


def _assert_error_envelope(response, *, status_code: int, code: str, message: str) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert "error" in payload
    assert "request_id" in payload
    assert "timestamp" in payload
    assert response.headers["X-Request-ID"] == payload["request_id"]
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == message
    return payload["error"]


def test_admin_health_live_response_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/admin/health/live")

    payload = _assert_success_envelope(response, status_code=200)
    assert payload["status"] == "alive"


def test_admin_health_ready_and_runtime_health_response_contracts(monkeypatch) -> None:
    current_user = {"value": _make_auth_user(role="manager")}

    async def override_current_user():
        return current_user["value"]

    async def fake_run_runtime_probe():
        return {
            "status": "ok",
            "checks": {
                "database": {"status": "ok"},
                "redis": {"status": "ok"},
                "kafka": {"status": "degraded"},
            },
        }

    monkeypatch.setattr(admin_health_router, "run_runtime_probe", fake_run_runtime_probe)
    monkeypatch.setattr(runtime_router, "run_runtime_probe", fake_run_runtime_probe)
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            ready_response = client.get("/v1/admin/health/ready")

            ready_payload = _assert_success_envelope(ready_response, status_code=200)
            assert ready_payload["status"] == "ok"
            assert ready_payload["checks"]["database"]["status"] == "ok"

            runtime_health_response = client.get("/v1/admin/runtime/health")

            runtime_health_payload = _assert_success_envelope(
                runtime_health_response, status_code=200
            )
            assert runtime_health_payload["status"] == "ok"
            assert runtime_health_payload["checks"]["kafka"]["status"] == "degraded"
    finally:
        app.dependency_overrides.clear()


def test_admin_runtime_probe_response_contract_and_role_guard() -> None:
    current_user = {"value": _make_auth_user(role="operator")}

    async def override_current_user():
        return current_user["value"]

    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            forbidden_response = client.get("/v1/admin/runtime/probe")

            forbidden_payload = _assert_error_envelope(
                forbidden_response,
                status_code=403,
                code="FORBIDDEN",
                message="Role is not allowed for this endpoint.",
            )
            assert forbidden_payload["details"]["actual_role"] == "operator"
            assert forbidden_payload["details"]["required_roles"] == ["admin", "manager"]

            current_user["value"] = _make_auth_user(role="admin")
            success_response = client.get("/v1/admin/runtime/probe")

            success_payload = _assert_success_envelope(success_response, status_code=200)
            assert success_payload["status"] in {"ok", "degraded"}
            assert set(success_payload["checks"].keys()) >= {"database", "redis", "kafka", "object_storage"}
    finally:
        app.dependency_overrides.clear()


def test_admin_users_list_response_contract() -> None:
    now = datetime.now(timezone.utc)
    customer = CustomerModel(
        id="cust-1",
        customer_code="CUST-TEST-0001",
        company_name="Integration Customer",
        contact_name="Alice",
        phone="13800000000",
        email="alice@example.com",
        address="Factory pickup",
        credit_limit=0,
        credit_used=0,
        price_level="standard",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    user_row = UserModel(
        id="user-1",
        username="operator-demo",
        email="operator@example.com",
        customer_id=customer.id,
        password_hash="secret",
        display_name="Operator Demo",
        role="customer",
        stage=None,
        scopes=[],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session = _FakeUsersSession(execute_results=[_RowsResult([(user_row, customer.company_name)])])

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="admin")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/users")

            payload = _assert_success_envelope(response, status_code=200)
            assert len(payload["items"]) == 1
            assert payload["items"][0]["id"] == "user-1"
            assert payload["items"][0]["customerName"] == "Integration Customer"
            assert payload["items"][0]["canonicalRole"] == "customer"
    finally:
        app.dependency_overrides.clear()


def test_admin_user_update_response_contract_and_bulk_success_error() -> None:
    now = datetime.now(timezone.utc)
    user_row = UserModel(
        id="user-1",
        username="manager-demo",
        email="manager@example.com",
        customer_id=None,
        password_hash="secret",
        display_name="Manager Demo",
        role="manager",
        stage=None,
        scopes=[],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session = _FakeUsersSession(get_map={(UserModel, "user-1"): user_row})

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="admin")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            update_response = client.put(
                "/v1/admin/users/user-1",
                json={"display_name": "Factory Manager"},
            )

            update_payload = _assert_success_envelope(update_response, status_code=200)
            assert update_payload["id"] == "user-1"
            assert update_payload["display_name"] == "Factory Manager"
            assert update_payload["canonicalRole"] == "manager"

            bulk_error_response = client.post(
                "/v1/admin/users/bulk",
                json={"action": "set_role", "user_ids": ["user-1"]},
            )

            bulk_error_payload = _assert_error_envelope(
                bulk_error_response,
                status_code=400,
                code="INVALID_BULK_ACTION",
                message="role is required when action is set_role",
            )
            assert bulk_error_payload["details"] == {}

            bulk_user_row = UserModel(
                id="user-1",
                username="manager-demo",
                email="manager@example.com",
                customer_id=None,
                password_hash="secret",
                display_name="Factory Manager",
                role="manager",
                stage=None,
                scopes=[],
                is_active=False,
                created_at=now,
                updated_at=now,
            )
            session._execute_results.extend(
                [
                    _RowCountResult(1),
                    _RowsResult([(bulk_user_row, None)]),
                ]
            )

            bulk_success_response = client.post(
                "/v1/admin/users/bulk",
                json={"action": "deactivate", "user_ids": ["user-1"]},
            )

            bulk_success_payload = _assert_success_envelope(bulk_success_response, status_code=200)
            assert bulk_success_payload["affected_count"] == 1
            assert len(bulk_success_payload["items"]) == 1
            assert bulk_success_payload["items"][0]["id"] == "user-1"
            assert bulk_success_payload["items"][0]["is_active"] is False
            assert bulk_success_payload["items"][0]["canonicalRole"] == "manager"
    finally:
        app.dependency_overrides.clear()


def test_admin_operators_response_contract() -> None:
    now = datetime.now(timezone.utc)
    operator_row = SimpleNamespace(
        id="operator-1",
        username="operator-demo",
        display_name="Operator Demo",
        email="operator@example.com",
        role="operator",
        is_active=True,
        created_at=now,
    )
    session = _FakeUsersSession(
        execute_results=[_ScalarRowsResult([operator_row])],
        scalar_results=[3],
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="manager")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/operators")

            payload = _assert_success_envelope(response, status_code=200)
            assert len(payload["items"]) == 1
            assert payload["items"][0]["id"] == "operator-1"
            assert payload["items"][0]["role"] == "operator"
            assert payload["items"][0]["unread_notifications"] == 3
    finally:
        app.dependency_overrides.clear()


def test_admin_acceptance_response_contract() -> None:
    now = datetime.now(timezone.utc)
    ready_order = SimpleNamespace(
        id="order-1",
        order_no="ORD-1001",
        customer_id="cust-1",
        status="ready_for_pickup",
        expected_delivery_date=now,
        updated_at=now,
    )
    failed_check = SimpleNamespace(
        id="qc-1",
        work_order_id="wo-1",
        inspector_id="user-1",
        check_type="final",
        result="failed",
        defect_qty=1,
        remark="Edge chipped",
        checked_at=now,
    )
    session = _FakeUsersSession(
        execute_results=[
            _ScalarRowsResult([ready_order]),
            _ScalarRowsResult([failed_check]),
        ],
        scalar_results=[2, 1, 1, 1],
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="admin")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/acceptance")

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["status"] == "attention"
            assert payload["kpis"] == {
                "ready_for_pickup_orders": 2,
                "picked_up_orders": 1,
                "in_transit_shipments": 1,
                "failed_quality_checks": 1,
            }
            assert payload["ready_for_pickup"][0]["id"] == "order-1"
            assert payload["failed_checks"][0]["id"] == "qc-1"
    finally:
        app.dependency_overrides.clear()


def test_admin_audit_logs_response_contract() -> None:
    now = datetime.now(timezone.utc)
    outbox_row = SimpleNamespace(
        id="evt-1",
        topic="orders.created",
        event_key="order-1",
        status="failed",
        attempt_count=2,
        max_attempts=5,
        last_error="broker unavailable",
        occurred_at=now,
        published_at=None,
        created_at=now,
        payload={"order_id": "order-1"},
        headers={"request_id": "req-1"},
    )
    session = _FakeUsersSession(
        execute_results=[_ScalarRowsResult([outbox_row]), _ScalarRowsResult([outbox_row])],
        scalar_results=[1, 4, 1, 4],
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="admin")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            alias_response = client.get("/v1/admin/audit", params={"status": "failed"})

            alias_payload = _assert_success_envelope(alias_response, status_code=200)
            assert alias_payload["summary"] == {"pending": 4, "dead_letter": 1}
            assert len(alias_payload["items"]) == 1
            assert alias_payload["items"][0]["id"] == "evt-1"
            assert alias_payload["items"][0]["status"] == "failed"

            response = client.get("/v1/admin/audit/logs")

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["summary"] == {"pending": 4, "dead_letter": 1}
            assert len(payload["items"]) == 1
            assert payload["items"][0]["id"] == "evt-1"
            assert payload["items"][0]["status"] == "failed"
            assert payload["items"][0]["payload"] == {"order_id": "order-1"}
    finally:
        app.dependency_overrides.clear()


def test_admin_runtime_alerts_response_contract(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    outbox_row = SimpleNamespace(
        id="evt-alert-1",
        topic="notifications.dispatch",
        event_key="notif-1",
        status="dead_letter",
        attempt_count=5,
        max_attempts=5,
        last_error="smtp timeout",
        created_at=now,
    )
    session = _FakeUsersSession(execute_results=[_ScalarRowsResult([outbox_row])])

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="manager")

    async def fake_collect_runtime_snapshot(_session) -> dict:
        return {
            "checks": {"database": True, "redis": True, "kafka": True},
            "redis_memory_used_bytes": 0.0,
            "redis_connected_clients": 0.0,
            "redis_memory_utilization_ratio": None,
            "clickhouse_up": True,
            "pgbouncer_waiting_clients": 0.0,
            "kafka_consumer_lag": 0.0,
            "outbox_records": {"pending": 0.0, "published": 0.0, "failed": 0.0, "dead_letter": 0.0},
        }

    monkeypatch.setattr(runtime_router, "collect_runtime_snapshot", fake_collect_runtime_snapshot)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/runtime/alerts")

            payload = _assert_success_envelope(response, status_code=200)
            assert len(payload["items"]) == 1
            assert payload["items"][0]["id"] == "evt-alert-1"
            assert payload["items"][0]["status"] == "dead_letter"
            assert payload["items"][0]["last_error"] == "smtp timeout"
    finally:
        app.dependency_overrides.clear()


def test_admin_runtime_alerts_include_threshold_breaches(monkeypatch) -> None:
    session = _FakeUsersSession(execute_results=[_ScalarRowsResult([])])

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="manager")

    async def fake_collect_runtime_snapshot(_session) -> dict:
        return {
            "checks": {"database": True, "redis": True, "kafka": True},
            "redis_memory_used_bytes": 1024.0,
            "redis_connected_clients": 5.0,
            "redis_memory_utilization_ratio": 0.9,
            "clickhouse_up": True,
            "pgbouncer_waiting_clients": 12.0,
            "kafka_consumer_lag": 250.0,
            "outbox_records": {"pending": 0.0, "published": 0.0, "failed": 0.0, "dead_letter": 0.0},
        }

    monkeypatch.setattr(runtime_router, "collect_runtime_snapshot", fake_collect_runtime_snapshot)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/runtime/alerts")

            payload = _assert_success_envelope(response, status_code=200)
            alert_ids = {item["id"] for item in payload["items"]}
            assert "runtime-threshold-pgbouncer-waiting" in alert_ids
            assert "runtime-threshold-redis-memory" in alert_ids
            assert "runtime-threshold-kafka-lag" in alert_ids
    finally:
        app.dependency_overrides.clear()


def test_admin_runtime_outbox_replay_response_contract(monkeypatch) -> None:
    session = _FakeUsersSession()

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="manager")

    async def fake_requeue_outbox_events(_session, *, ids=None, statuses=None, limit=100):
        assert _session is session
        assert ids == []
        assert statuses == ["dead_letter"]
        assert limit == 25
        return [
            SimpleNamespace(id="evt-dead-1"),
            SimpleNamespace(id="evt-dead-2"),
        ]

    monkeypatch.setattr(runtime_router, "requeue_outbox_events", fake_requeue_outbox_events)
    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/runtime/outbox/replay",
                json={"statuses": ["dead_letter"], "limit": 25},
            )

            payload = _assert_success_envelope(response, status_code=200)
            assert payload == {
                "requested_statuses": ["dead_letter"],
                "requested_ids": [],
                "replayed": 2,
                "replayed_ids": ["evt-dead-1", "evt-dead-2"],
                "missing_ids": [],
            }
            assert session.commit_calls == 1
    finally:
        app.dependency_overrides.clear()


def test_admin_analytics_response_contracts() -> None:
    current_session = {"value": _FakeUsersSession(scalar_results=[2, 10, 3, 2, 5, 4])}

    async def override_session() -> AsyncGenerator:
        yield current_session["value"]

    async def override_current_user():
        return _make_auth_user(role="manager")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            overview_response = client.get("/v1/admin/analytics/overview")

            overview_payload = _assert_success_envelope(overview_response, status_code=200)
            assert overview_payload["kpis"] == {
                "orders_today": 2,
                "total_orders": 10,
                "pending_orders": 3,
                "producing_orders": 2,
                "completed_orders": 5,
                "active_work_orders": 4,
            }

            current_session["value"] = _FakeUsersSession(
                execute_results=[
                    _RowsResult([("in_progress", 2), ("pending", 1)]),
                    _RowsResult([("line-1", "LN-01", "Cutting Line", 3)]),
                ]
            )
            production_response = client.get("/v1/admin/analytics/production")

            production_payload = _assert_success_envelope(production_response, status_code=200)
            assert production_payload["status_breakdown"] == {"in_progress": 2, "pending": 1}
            assert production_payload["lines"][0] == {
                "line_id": "line-1",
                "line_code": "LN-01",
                "line_name": "Cutting Line",
                "work_order_count": 3,
            }

            current_session["value"] = _FakeUsersSession(
                scalar_results=[3, Decimal("1200.00")],
                execute_results=[_RowsResult([("completed", 2), ("pending", 1)])],
            )
            sales_response = client.get("/v1/admin/analytics/sales", params={"days": 7})

            sales_payload = _assert_success_envelope(sales_response, status_code=200)
            assert sales_payload["window_days"] == 7
            assert sales_payload["orders"] == 3
            assert Decimal(str(sales_payload["total_sales"])) == Decimal("1200.0")
            assert Decimal(str(sales_payload["avg_order_amount"])) == Decimal("400.0")
            assert sales_payload["status_breakdown"] == {"completed": 2, "pending": 1}
    finally:
        app.dependency_overrides.clear()


def test_admin_tasks_response_contract() -> None:
    now = datetime.now(timezone.utc)
    session = _FakeUsersSession(
        execute_results=[
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="evt-1",
                        topic="orders.created",
                        attempt_count=2,
                        max_attempts=5,
                        last_error="broker unavailable",
                        created_at=now,
                    )
                ]
            ),
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="recv-1",
                        order_id="order-1",
                        customer_id="cust-1",
                        amount=Decimal("200.00"),
                        paid_amount=Decimal("50.00"),
                        status="partial",
                        due_date=date(2026, 4, 1),
                    )
                ]
            ),
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="wo-1",
                        work_order_no="WO-1001",
                        status="pending",
                        glass_type="Tempered",
                        specification="6mm",
                        quantity=3,
                        created_at=now,
                    )
                ]
            ),
            _ScalarRowsResult(
                [
                    SimpleNamespace(
                        id="order-2",
                        order_no="ORD-1002",
                        status="ready_for_pickup",
                        expected_delivery_date=now,
                        updated_at=now,
                    )
                ]
            ),
        ],
        scalar_results=[1, 2, 3, 4],
    )

    async def override_session() -> AsyncGenerator:
        yield session

    async def override_current_user():
        return _make_auth_user(role="admin")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            response = client.get("/v1/admin/tasks", params={"limit": 10})

            payload = _assert_success_envelope(response, status_code=200)
            assert payload["summary"] == {
                "dead_letter_events": 1,
                "overdue_receivables": 2,
                "unscheduled_work_orders": 3,
                "pickup_approvals": 4,
            }
            assert len(payload["items"]) == 4
            assert payload["items"][0]["task_type"] == "event_retry"
            assert payload["items"][1]["task_type"] == "receivable_overdue"
            assert payload["items"][2]["task_type"] == "schedule_work_order"
            assert payload["items"][3]["task_type"] == "pickup_approval"
    finally:
        app.dependency_overrides.clear()


def test_admin_production_line_response_contracts() -> None:
    now = datetime.now(timezone.utc)
    line_row = SimpleNamespace(
        id="line-1",
        line_code="LN-01",
        line_name="Cutting Line",
        supported_glass_types=["Tempered"],
        max_width_mm=3000,
        max_height_mm=2000,
        daily_capacity_sqm=Decimal("42.50"),
        supported_processes=["cutting"],
        is_active=True,
        created_at=now,
    )
    current_session = {
        "value": _FakeUsersSession(
            execute_results=[
                _ScalarRowsResult([line_row]),
                _RowsResult([("line-1", 2)]),
            ]
        )
    }

    async def override_session() -> AsyncGenerator:
        yield current_session["value"]

    async def override_current_user():
        return _make_auth_user(role="manager")

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user] = override_current_user

    try:
        with TestClient(app) as client:
            list_response = client.get("/v1/admin/production/lines", params={"active_only": True})

            list_payload = _assert_success_envelope(list_response, status_code=200)
            assert len(list_payload["items"]) == 1
            assert list_payload["items"][0]["id"] == "line-1"
            assert list_payload["items"][0]["active_work_orders"] == 2
            assert Decimal(str(list_payload["items"][0]["daily_capacity_sqm"])) == Decimal("42.5")

            current_session["value"] = _FakeUsersSession(
                get_map={(ProductionLineModel, "line-1"): line_row}
            )
            missing_response = client.put(
                "/v1/admin/production/lines/missing-line",
                json={"line_name": "Updated Line"},
            )

            missing_payload = _assert_error_envelope(
                missing_response,
                status_code=404,
                code="PRODUCTION_LINE_NOT_FOUND",
                message="Production line not found: missing-line",
            )
            assert missing_payload["details"] == {}

            update_response = client.put(
                "/v1/admin/production/lines/line-1",
                json={"line_name": "Updated Line", "is_active": False},
            )

            update_payload = _assert_success_envelope(update_response, status_code=200)
            assert update_payload["id"] == "line-1"
            assert update_payload["line_name"] == "Updated Line"
            assert update_payload["is_active"] is False

            current_session["value"] = _FakeUsersSession(execute_results=[_ScalarRowsResult([])])
            schedule_response = client.post("/v1/admin/production/schedule", json={})

            schedule_payload = _assert_error_envelope(
                schedule_response,
                status_code=409,
                code="PRODUCTION_LINE_NOT_CONFIGURED",
                message="No active production lines are configured.",
            )
            assert schedule_payload["details"] == {}

            work_order_row = SimpleNamespace(
                id="wo-1",
                order_id="order-1",
                order_item_id="item-1",
                glass_type="Tempered",
                specification="6mm",
                width_mm=1000,
                height_mm=500,
                quantity=2,
                status="pending",
                created_at=now,
                scheduled_date=None,
                production_line_id=None,
            )
            order_row = SimpleNamespace(
                id="order-1",
                order_no="ORD-1001",
                expected_delivery_date=datetime(2026, 4, 18, tzinfo=timezone.utc),
                remark="rush order",
            )
            order_item_row = SimpleNamespace(process_requirements="cutting")
            current_session["value"] = _FakeUsersSession(
                execute_results=[
                    _ScalarRowsResult([line_row]),
                    _RowsResult([(work_order_row, order_row, order_item_row)]),
                ]
            )
            schedule_success_response = client.post(
                "/v1/admin/production/schedule",
                json={
                    "day": "2026-04-14",
                    "horizon_days": 5,
                    "work_order_ids": ["wo-1", "missing-wo"],
                },
            )

            schedule_success_payload = _assert_success_envelope(
                schedule_success_response,
                status_code=200,
            )
            assert schedule_success_payload["scheduled_day"] == "2026-04-14"
            assert schedule_success_payload["scheduled_count"] == 1
            assert schedule_success_payload["scheduled_work_order_ids"] == ["wo-1"]
            assert schedule_success_payload["scheduled_slots"] == [
                {
                    "work_order_id": "wo-1",
                    "line_id": "line-1",
                    "scheduled_date": "2026-04-14",
                    "sequence": 1,
                }
            ]
            assert schedule_success_payload["unscheduled_work_order_ids"] == ["missing-wo"]
            assert work_order_row.production_line_id == "line-1"
            assert work_order_row.scheduled_date == date(2026, 4, 14)
    finally:
        app.dependency_overrides.clear()
