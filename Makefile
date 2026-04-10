PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
UVICORN ?= uvicorn
LOCUST ?= $(PYTHON) -m locust

.PHONY: install format lint test test-unit test-integration test-contract test-e2e test-load-import run-public-api run-admin-api run-scheduler migrate qa-ci load-baseline load-report-init ops-stack-up ops-backup-baseline ops-restore-baseline ops-compose-load-baseline

install:
	$(PIP) install -r requirements.txt

format:
	black .
	isort .

lint:
	black --check apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py tests/unit tests/integration tests/e2e tests/load
	isort --check-only apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py tests/unit tests/integration tests/e2e tests/load
	mypy --follow-imports=silent apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py

test:
	pytest

test-unit:
	pytest tests/unit

test-integration:
	pytest tests/integration

test-contract:
	pytest tests/contract

test-e2e:
	pytest tests/e2e

test-load-import:
	$(PYTHON) tests/load/validate_env.py
	$(PYTHON) -m py_compile tests/load/locustfile.py tests/load/validate_env.py

run-public-api:
	$(UVICORN) apps.public_api.main:app --host 0.0.0.0 --port 8000 --reload

run-admin-api:
	$(UVICORN) apps.admin_api.main:app --host 0.0.0.0 --port 8001 --reload

run-scheduler:
	$(PYTHON) -m apps.scheduler

migrate:
	alembic upgrade head

qa-ci: lint test-unit test-integration test-contract test-e2e test-load-import

load-baseline:
	$(LOCUST) -f tests/load/locustfile.py --headless -u 50 -r 10 -t 2m --host $${LOAD_BASE_URL:-http://localhost:8000}

load-report-init:
	mkdir -p reports/load
	@echo "Load reports directory initialized at reports/load"

ops-stack-up:
	sh ops/bin/compose-up.sh

ops-backup-baseline:
	sh ops/bin/backup-baseline.sh

ops-restore-baseline:
	sh ops/bin/restore-baseline.sh

ops-compose-load-baseline:
	sh ops/bin/compose-load-baseline.sh
