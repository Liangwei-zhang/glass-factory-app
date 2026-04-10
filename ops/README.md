# Ops Overview

This directory contains deployment and runtime assets for the FastAPI modular monolith.

## Quick Start

```bash
cd ops
docker compose up -d --build
```

## Included Components

- `docker-compose.yml`: local full stack baseline
- `nginx/default.conf`: edge proxy for public/admin APIs
- `pgbouncer/`: transaction pooling layer
- `minio/`: object storage bootstrap helpers
- `runbooks/`: operational procedures
- `bin/`: helper scripts for compose, backup, and restore
