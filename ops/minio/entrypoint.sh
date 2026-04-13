#!/usr/bin/env sh
set -eu

mc alias set local http://minio:9000 "${MINIO_ROOT_USER:-minio}" "${MINIO_ROOT_PASSWORD:-minio12345}"
mc mb -p local/glass-factory || true
mc anonymous set none local/glass-factory || true
