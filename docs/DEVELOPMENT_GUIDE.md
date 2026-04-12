# Development Guide

The canonical architecture and implementation spec is maintained in `sj.md`.

## Local Commands

```bash
make install
make run-public-api
make run-admin-api
```

## Quality Commands

```bash
make test-guardrails
make lint
make test
```

## Guardrails

- S0 execution guardrails are defined in `docs/ARCHITECTURE_GUARDRAILS.md`.
- Read-path cache policy must be declared in `docs/CACHE_STRATEGY_MATRIX.md` before a new read surface merges.
- `backend/` is a frozen legacy runtime: blocking fixes only, no new source files or new feature work.
- `make test-guardrails` is the fast preflight check for the legacy backend freeze and required guardrail docs.

## Notes

- Keep routers thin: route validation and service orchestration only.
- Keep repositories focused on persistence only.
- Publish cross-domain side effects through outbox events.
