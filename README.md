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

## Notes

- The previous Node.js MVP implementation remains in `backend/` as a legacy reference while Python implementation progresses.
- The canonical product/architecture design is documented in `sj.md`.
