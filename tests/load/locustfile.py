from __future__ import annotations

import os
from uuid import uuid4

from locust import HttpUser, between, task

SIGNATURE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+s4e0AAAAASUVORK5CYII="
)


def _task_weight(env_name: str, default: int) -> int:
    raw_value = os.getenv(env_name, str(default)).strip()
    if not raw_value:
        return default
    try:
        return max(0, int(raw_value))
    except ValueError:
        return default


class PublicApiUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.access_token: str | None = None
        self.workspace_role: str | None = None
        self.workspace_customer_id: str | None = os.getenv("LOCUST_WORKSPACE_CUSTOMER_ID", "").strip() or None
        self.enable_workspace_full_lifecycle = os.getenv(
            "LOCUST_WORKSPACE_FULL_LIFECYCLE",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}

        workspace_email = os.getenv("LOCUST_WORKSPACE_EMAIL", "").strip()
        workspace_password = os.getenv("LOCUST_WORKSPACE_PASSWORD", "").strip()
        if not workspace_email or not workspace_password:
            return

        login_response = self.client.post(
            "/v1/workspace/auth/login",
            json={"email": workspace_email, "password": workspace_password},
            headers={"Idempotency-Key": self._idempotency_key()},
            name="POST /v1/workspace/auth/login",
        )
        if not login_response.ok:
            return

        payload = self._unwrap_response(login_response)
        self.access_token = payload.get("token") or payload.get("access_token")
        workspace_user = payload.get("user") or {}
        self.workspace_role = (
            workspace_user.get("canonicalRole")
            or workspace_user.get("role")
            or ""
        ).strip().lower() or None
        if not self.access_token or self.workspace_customer_id:
            return

        bootstrap_response = self.client.get(
            "/v1/workspace/bootstrap",
            headers=self._auth_headers(),
            name="GET /v1/workspace/bootstrap",
        )
        if not bootstrap_response.ok:
            return

        bootstrap_payload = self._unwrap_response(bootstrap_response)
        customers = ((bootstrap_payload.get("data") or {}).get("customers") or [])
        if customers:
            self.workspace_customer_id = customers[0].get("id")

    def _idempotency_key(self) -> str:
        return str(uuid4())

    def _unwrap_response(self, response):
        payload = response.json()
        return payload.get("data", payload)

    def _auth_headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _manager_like_workspace_user(self) -> bool:
        return self.workspace_role in {"manager", "admin", "super_admin"}

    def _workspace_create_order(self, *, quantity: str, name: str):
        return self.client.post(
            "/v1/workspace/orders",
            data={
                "customerId": self.workspace_customer_id,
                "glassType": "Tempered",
                "thickness": "6mm",
                "quantity": quantity,
                "priority": "normal",
                "estimatedCompletionDate": "2026-04-12",
                "specialInstructions": "locust hot path",
            },
            files={},
            headers=self._auth_headers(self._idempotency_key()),
            name=name,
        )

    @task(_task_weight("LOCUST_WEIGHT_HEALTH_LIVE", 5))
    def health_live(self) -> None:
        self.client.get("/v1/health/live", name="GET /v1/health/live")

    @task(_task_weight("LOCUST_WEIGHT_HEALTH_READY", 2))
    def health_ready(self) -> None:
        self.client.get("/v1/health/ready", name="GET /v1/health/ready")

    @task(_task_weight("LOCUST_WEIGHT_METRICS", 1))
    def metrics(self) -> None:
        self.client.get("/v1/monitoring/metrics", name="GET /v1/monitoring/metrics")

    @task(_task_weight("LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS", 2))
    def workspace_list_orders(self) -> None:
        if not self.access_token:
            return
        self.client.get(
            "/v1/workspace/orders",
            headers=self._auth_headers(),
            name="GET /v1/workspace/orders",
        )

    @task(_task_weight("LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL", 1))
    def workspace_create_then_cancel_order(self) -> None:
        if not self.access_token or not self.workspace_customer_id:
            return

        create_response = self._workspace_create_order(
            quantity="1",
            name="POST /v1/workspace/orders",
        )
        if not create_response.ok:
            return

        created_payload = self._unwrap_response(create_response)
        order = created_payload.get("order") or {}
        order_id = order.get("id")
        if not order_id:
            return

        self.client.post(
            f"/v1/workspace/orders/{order_id}/cancel",
            json={"reason": "locust cleanup"},
            headers=self._auth_headers(self._idempotency_key()),
            name="POST /v1/workspace/orders/{order_id}/cancel",
        )

    @task(_task_weight("LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE", 1))
    def workspace_full_order_lifecycle(self) -> None:
        if (
            not self.enable_workspace_full_lifecycle
            or not self.access_token
            or not self.workspace_customer_id
            or not self._manager_like_workspace_user()
        ):
            return

        create_response = self._workspace_create_order(
            quantity="1",
            name="POST /v1/workspace/orders [lifecycle]",
        )
        if not create_response.ok:
            return

        created_payload = self._unwrap_response(create_response)
        order = created_payload.get("order") or {}
        order_id = order.get("id")
        if not order_id:
            return

        if not self.client.post(
            f"/v1/workspace/orders/{order_id}/entered",
            headers=self._auth_headers(self._idempotency_key()),
            name="POST /v1/workspace/orders/{order_id}/entered",
        ).ok:
            return

        for step_key in ["cutting", "edging", "tempering", "finishing"]:
            step_response = self.client.post(
                f"/v1/workspace/orders/{order_id}/steps/{step_key}",
                json={"action": "complete"},
                headers=self._auth_headers(self._idempotency_key()),
                name="POST /v1/workspace/orders/{order_id}/steps/{step_key}",
            )
            if not step_response.ok:
                return

        if not self.client.post(
            f"/v1/workspace/orders/{order_id}/pickup/approve",
            headers=self._auth_headers(self._idempotency_key()),
            name="POST /v1/workspace/orders/{order_id}/pickup/approve",
        ).ok:
            return

        self.client.post(
            f"/v1/workspace/orders/{order_id}/pickup/signature",
            json={
                "signerName": "Locust Receiver",
                "signatureDataUrl": SIGNATURE_DATA_URL,
            },
            headers=self._auth_headers(self._idempotency_key()),
            name="POST /v1/workspace/orders/{order_id}/pickup/signature",
        )
