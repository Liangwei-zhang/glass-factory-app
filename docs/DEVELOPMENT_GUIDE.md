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
make lint
make test
```

## Notes

- Keep routers thin: route validation and service orchestration only.
- Keep repositories focused on persistence only.
- Publish cross-domain side effects through outbox events.
