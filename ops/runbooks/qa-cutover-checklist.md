# QA Cutover Checklist

- [ ] Public API `/v1/health/ready` returns `ok` or expected degraded details.
- [ ] Admin API `/v1/admin/runtime/probe` is reachable through Nginx.
- [ ] Login and order creation workflows are validated in staging.
- [ ] Inventory reservation conflict case is tested.
- [ ] Outbox has no stuck `pending` rows after integration tests.
- [ ] Alembic upgrade can run from clean database.
- [ ] Rollback plan and latest backup are available.
