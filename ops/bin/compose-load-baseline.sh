#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "$(dirname "$SCRIPT_DIR")")

PYTHON_BIN=${PYTHON_BIN:-python3}
LOAD_PYTHON_SITE_PACKAGES=${LOAD_PYTHON_SITE_PACKAGES:-$PROJECT_ROOT/.cache/load-baseline/site-packages}
LOAD_BASE_URL=${LOAD_BASE_URL:-http://localhost:8000}
LOAD_USERS=${LOAD_USERS:-50}
LOAD_SPAWN_RATE=${LOAD_SPAWN_RATE:-10}
LOAD_DURATION=${LOAD_DURATION:-10m}
LOAD_REQUIRE_WORKSPACE_AUTH=${LOAD_REQUIRE_WORKSPACE_AUTH:-1}
LOAD_REPORT_BASENAME=${LOAD_REPORT_BASENAME:-reports/load/baseline-$(date -u +%Y%m%d-%H%M%S)}
LOCUST_WORKSPACE_FULL_LIFECYCLE=${LOCUST_WORKSPACE_FULL_LIFECYCLE:-1}
LOCUST_WEIGHT_HEALTH_LIVE=${LOCUST_WEIGHT_HEALTH_LIVE:-1}
LOCUST_WEIGHT_HEALTH_READY=${LOCUST_WEIGHT_HEALTH_READY:-1}
LOCUST_WEIGHT_METRICS=${LOCUST_WEIGHT_METRICS:-0}
LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS=${LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS:-4}
LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL=${LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL:-3}
LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE=${LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE:-2}

cd "$PROJECT_ROOT"
mkdir -p "$(dirname "$LOAD_REPORT_BASENAME")"
mkdir -p "$LOAD_PYTHON_SITE_PACKAGES"
export PYTHONPATH="$LOAD_PYTHON_SITE_PACKAGES:$PROJECT_ROOT/tests/load/pythonpath${PYTHONPATH:+:$PYTHONPATH}"
export LOAD_BASE_URL LOAD_USERS LOAD_SPAWN_RATE LOAD_DURATION LOAD_REQUIRE_WORKSPACE_AUTH LOAD_REPORT_BASENAME
export LOCUST_WORKSPACE_FULL_LIFECYCLE LOCUST_WEIGHT_HEALTH_LIVE LOCUST_WEIGHT_HEALTH_READY
export LOCUST_WEIGHT_METRICS LOCUST_WEIGHT_WORKSPACE_LIST_ORDERS LOCUST_WEIGHT_WORKSPACE_CREATE_CANCEL
export LOCUST_WEIGHT_WORKSPACE_FULL_LIFECYCLE
"$PYTHON_BIN" tests/load/validate_env.py
"$PYTHON_BIN" -m py_compile tests/load/locustfile.py tests/load/validate_env.py tests/load/write_report_archive.py tests/load/pythonpath/sitecustomize.py tests/load/pythonpath/zope/__init__.py
"$PYTHON_BIN" -m pip install --upgrade --target "$LOAD_PYTHON_SITE_PACKAGES" -r requirements.txt
set +e
"$PYTHON_BIN" -m locust \
	-f tests/load/locustfile.py \
	--headless \
	-u "$LOAD_USERS" \
	-r "$LOAD_SPAWN_RATE" \
	-t "$LOAD_DURATION" \
	--host "$LOAD_BASE_URL" \
	--csv "$LOAD_REPORT_BASENAME" \
	--html "$LOAD_REPORT_BASENAME.html"
locust_status=$?
set -e
"$PYTHON_BIN" tests/load/write_report_archive.py
printf 'load baseline reports: %s_stats.csv, %s_failures.csv, %s_exceptions.csv, %s.html\n' \
	"$LOAD_REPORT_BASENAME" \
	"$LOAD_REPORT_BASENAME" \
	"$LOAD_REPORT_BASENAME" \
	"$LOAD_REPORT_BASENAME"
printf 'load baseline archive template: %s.summary.md\n' "$LOAD_REPORT_BASENAME"
exit "$locust_status"
