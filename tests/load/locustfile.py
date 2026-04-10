from __future__ import annotations

from locust import HttpUser, between, task


class PublicApiUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(5)
    def health_live(self) -> None:
        self.client.get("/v1/health/live", name="GET /v1/health/live")

    @task(2)
    def health_ready(self) -> None:
        self.client.get("/v1/health/ready", name="GET /v1/health/ready")

    @task(1)
    def metrics(self) -> None:
        self.client.get("/v1/monitoring/metrics", name="GET /v1/monitoring/metrics")
