# Architecture Guardrails

This file turns the S0 execution guardrails from `todo.md` into merge-time rules.

## Canonical Paths

- New product features belong in `apps/`, `domains/`, `infra/`, `alembic/`, `tests/`, and `docs/`.
- `/api/*` compatibility is closed for feature work.
- `backend/` is a legacy runtime and is not a valid destination for new feature delivery.

## Legacy Backend Freeze

- `backend/` is frozen for migration and blocking-fix work only.
- Allowed work in `backend/`: blocker fixes, migration shims, and forensic reads while behavior is being moved to the Python stack.
- Disallowed work in `backend/`: new endpoints, new domain behavior, new persistence paths, and new source files.
- The current legacy file set is snapshotted in `ops/policy/legacy_backend_allowlist.txt` and enforced by `make test-guardrails`.

## Layering Rules

- Router: request validation, auth checks, response shaping, and service orchestration only.
- Service: business rules, transaction boundaries, cache hook registration, and event publication.
- Repository: persistence only; no SMTP, object storage, HTTP, broker, or other external I/O.
- Cross-domain side effects must be published through Outbox + EventBus subscribers, not direct service-to-service chaining.

## Delivery Checklist

- New behavior ships with the relevant domain/service/repository/router changes together.
- Data-shape changes ship with the matching ORM and Alembic migration updates.
- Cross-domain capabilities update `infra/events/topics.py`, add the outbox publish point, add the subscriber/worker path, and add regression coverage.
- New or changed behavior updates the relevant docs before it claims completion.

## Read-Path Cache Policy

Before merging a new read path:

1. Add or update its row in `docs/CACHE_STRATEGY_MATRIX.md`.
2. Declare the cache key, TTL, fill trigger, refresh trigger, invalidation trigger, and stale-data fallback.
3. Prefer cache-after-commit invalidation or refresh via `infra.core.hooks` when the read path depends on mutable OLTP state.
4. If a route intentionally ships without cache, record that decision explicitly in the matrix instead of leaving the policy undefined.