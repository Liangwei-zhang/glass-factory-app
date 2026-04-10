# Backup and Restore Runbook

## Backup

1. Ensure `gf-postgres` container is running.
2. Run:

```bash
ops/bin/backup-baseline.sh ./backups
```

3. Verify generated SQL file size and checksum.

## Restore

1. Stop write traffic to APIs.
2. Run:

```bash
ops/bin/restore-baseline.sh ./backups/<file>.sql
```

3. Run smoke checks on `/v1/health/ready` and order read APIs.
