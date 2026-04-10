#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OPS_DIR=$(dirname "$SCRIPT_DIR")

cd "$OPS_DIR"
docker compose up -d --build
