#!/usr/bin/env sh
set -eu

BACKUP_DIR=${1:-./backups}
mkdir -p "$BACKUP_DIR"

DATE_TAG=$(date +%Y%m%d_%H%M%S)
OUT_FILE="$BACKUP_DIR/postgres_${DATE_TAG}.sql"

docker exec gf-postgres pg_dump -U postgres glass_factory > "$OUT_FILE"
echo "Backup written to $OUT_FILE"
