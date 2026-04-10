#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname "$(dirname "$SCRIPT_DIR")")

PYTHON_BIN=${PYTHON_BIN:-python3}
LOAD_BASE_URL=${LOAD_BASE_URL:-http://localhost:8000}
LOAD_USERS=${LOAD_USERS:-50}
LOAD_SPAWN_RATE=${LOAD_SPAWN_RATE:-10}
LOAD_DURATION=${LOAD_DURATION:-2m}

cd "$PROJECT_ROOT"
"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" -m locust -f tests/load/locustfile.py --headless -u "$LOAD_USERS" -r "$LOAD_SPAWN_RATE" -t "$LOAD_DURATION" --host "$LOAD_BASE_URL"
