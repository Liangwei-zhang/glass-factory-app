# Glass Factory App

This repository is now aligned to the `sj.md` architecture: a Python modular monolith built with FastAPI, SQLAlchemy async, PostgreSQL, and Redis.

## Architecture

- `apps/public_api`: public-facing API (`:8000`)
- `apps/admin_api`: admin API (`:8001`)
- `domains/*`: business domain modules (orders, inventory, production, customers, logistics, finance, notifications, auth)
- `infra/*`: database, cache, events/outbox, security, observability, storage, analytics
- `apps/workers/*`: worker entry points (event pipeline, timeout, sync, scheduler, retention)
- `ops/`: compose, nginx, pgbouncer, runbooks, scripts

## Local Setup

1. Install Python dependencies in your environment.
2. Copy `.env.example` to `.env` and adjust database/redis settings.
3. Run migrations:

```bash
alembic upgrade head
```

4. Start APIs:

```bash
make run-public-api
make run-admin-api
```

## Compose Setup

```bash
ops/bin/compose-up.sh
```

Services exposed:

- `http://localhost:8080` (Nginx edge)
- `http://localhost:8000/docs` (Public API docs)
- `http://localhost:8001/docs` (Admin API docs)

## QA Commands

```bash
make lint
make test
python3 -m compileall apps domains infra alembic
```

Real Postgres + Redis inventory integration is opt-in and expects disposable infra endpoints:

```bash
INTEGRATION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/glass_factory_test \
INTEGRATION_REDIS_URL=redis://localhost:6379/15 \
pytest tests/integration/test_real_inventory_reservation_flow.py tests/integration/test_real_orders_service_flow.py -q
```

Notes:

- `INTEGRATION_DATABASE_URL` must point to a dedicated test database because the suite recreates the SQLAlchemy schema.
- `INTEGRATION_REDIS_URL` must point to a dedicated Redis DB because the suite flushes it before and after each test.
- The real-infra suite now covers both the Redis reservation layer and the formal `OrdersService` main path against Postgres + Redis.

## Load Testing

Basic health and hot-path load testing uses Locust:

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Stable baseline runs are captured with a dedicated 10-minute command that writes CSV + HTML reports:

```bash
make load-baseline-stable
```

Optional environment variables enable the authenticated `/v1/workspace` hot path:

- `LOCUST_WORKSPACE_EMAIL`: workspace operator/manager email used for login.
- `LOCUST_WORKSPACE_PASSWORD`: matching password for the workspace account.
- `LOCUST_WORKSPACE_CUSTOMER_ID`: customer id used when creating workspace orders; if omitted, Locust will try to use the first customer from `/v1/workspace/bootstrap`.
- `LOCUST_WORKSPACE_FULL_LIFECYCLE`: set to `1`/`true` to run an additional create -> entered -> finishing -> pickup signature lifecycle task. This requires a manager/admin-like workspace account because one account must be able to complete every production step and pickup approval.
- `LOAD_REPORT_BASENAME`: optional output prefix for baseline artifacts; defaults to `reports/load/baseline-<timestamp>`.
- `LOCUST_WEIGHT_HEALTH_LIVE`, `LOCUST_WEIGHT_HEALTH_READY`, `LOCUST_WEIGHT_METRICS`, `LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS`, `LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL`, `LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE`: optional non-negative integer weights for each Locust scenario.

`make load-baseline-stable` requires `LOCUST_WORKSPACE_EMAIL` and `LOCUST_WORKSPACE_PASSWORD` so the run always exercises the authenticated `/v1/workspace` order hot path instead of health probes only.
Each stable baseline run now also writes a companion `*.summary.md` archive template next to the CSV/HTML artifacts so operators can fill in the observed latency, error rate, and follow-up notes.
The wrapper now preserves the CSV, HTML, and summary artifacts even when Locust exits non-zero because the run exposed failures, so unsuccessful baselines can still be triaged from `reports/load/` instead of being discarded.
On Linux environments with PEP 668 system Python enforcement, the baseline script now bootstraps its Python dependencies into a project-local site-packages cache under `.cache/load-baseline/` so `make load-baseline-stable` can run without requiring a virtualenv or mutating the broader user environment.
Latest local compose-backed rerun after the Redis stock-snapshot refresh and workspace batch-serialization fixes is archived at `reports/load/baseline-real-20260410-221813.*`: 8729 requests, peak 30.5 req/s, aggregated p95 20s, `GET /v1/workspace/orders` p95 1.8s, and 2 transport-level `RemoteDisconnected` failures (0.02%) with no remaining business 409 conflicts.

## Notes

- The previous Node.js MVP implementation remains in `backend/` as a legacy reference while Python implementation progresses.
- The canonical product/architecture design is documented in `sj.md`.
