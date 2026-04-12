PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
UVICORN ?= uvicorn
LOCUST ?= $(PYTHON) -m locust
PYTEST_PYTHONPATH ?= $(CURDIR)/.cache/pytest8
PYTEST ?= PYTHONPATH=$(PYTEST_PYTHONPATH) $(PYTHON) -m pytest
BLACK ?= $(PYTHON) -m black
ISORT ?= $(PYTHON) -m isort
MYPY ?= $(PYTHON) -m mypy

.PHONY: install format lint test test-guardrails test-unit test-integration test-contract test-e2e test-load-import run-public-api run-admin-api run-scheduler migrate qa-ci load-baseline load-baseline-stable load-report-init ops-stack-up ops-backup-baseline ops-restore-baseline ops-compose-load-baseline

install:
	$(PIP) install -r requirements.txt

format:
	$(BLACK) .
	$(ISORT) .

lint:
	$(BLACK) --check apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py tests/unit tests/integration tests/e2e tests/load
	$(ISORT) --check-only apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py tests/unit tests/integration tests/e2e tests/load
	$(MYPY) --follow-imports=silent apps/scheduler apps/workers domains/production apps/admin_api/routers/production_admin.py infra/events infra/observability/runtime_probe.py infra/core/config.py infra/analytics/clickhouse_client.py

test:
	$(PYTEST)

test-guardrails:
	$(PYTEST) tests/guardrails

test-unit:
	$(PYTEST) tests/unit

test-integration:
	$(PYTEST) tests/integration

test-contract:
	$(PYTEST) tests/contract

test-e2e:
	$(PYTEST) tests/e2e

test-load-import:
	$(PYTHON) tests/load/validate_env.py
	$(PYTHON) -m py_compile tests/load/locustfile.py tests/load/validate_env.py tests/load/write_report_archive.py tests/load/pythonpath/sitecustomize.py tests/load/pythonpath/zope/__init__.py

run-public-api:
	$(UVICORN) apps.public_api.main:app --host 0.0.0.0 --port 8000 --reload

run-admin-api:
	$(UVICORN) apps.admin_api.main:app --host 0.0.0.0 --port 8001 --reload

run-scheduler:
	$(PYTHON) -m apps.scheduler

migrate:
	alembic upgrade head

qa-ci: test-guardrails lint test-unit test-integration test-contract test-e2e test-load-import

load-baseline:
	$(LOCUST) -f tests/load/locustfile.py --headless -u 50 -r 10 -t 2m --host $${LOAD_BASE_URL:-http://localhost:8000}

load-baseline-stable:
	sh ops/bin/compose-load-baseline.sh

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
