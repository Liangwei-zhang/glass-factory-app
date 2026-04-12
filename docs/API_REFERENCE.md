# API Reference

## Public Orders API

- `POST /v1/auth/login`
- `GET /v1/health/live`
- `GET /v1/health/ready`
- `GET /v1/inventory`
- `POST /v1/orders`
- `GET /v1/orders`
- `GET /v1/orders/{order_id}`
- `PUT /v1/orders/{order_id}`
- `POST /v1/orders/{order_id}/entered`
- `POST /v1/orders/{order_id}/steps/{step_key}`
- `POST /v1/orders/{order_id}/pickup/approve`
- `POST /v1/orders/{order_id}/pickup/send-email`
- `POST /v1/orders/{order_id}/pickup/signature`

Notes:
- `POST /v1/orders` requires `orders:write` scope and `Idempotency-Key`, returns `201`, and duplicate writes are rejected with `409`.
- Success responses are wrapped in the standard `{ data, request_id, timestamp }` envelope.

## Customers API

- `GET /v1/customers/profile`
- `GET /v1/customers/credit`
- `GET /v1/customers`
- `POST /v1/customers`

Notes:
- `POST /v1/customers` requires `Idempotency-Key`.
- Customer-facing reads follow the same `{ data, request_id, timestamp }` success envelope and the standard error envelope.

## Notifications API

- `GET /v1/notifications`
- `PUT /v1/notifications/read`

Notes:
- Mark-read requires `Idempotency-Key`.
- List and write responses both use the standard response envelope.

## Logistics API

- `GET /v1/logistics/shipments`
- `POST /v1/logistics/shipments`
- `POST /v1/logistics/shipments/{shipment_id}/deliver`
- `GET /v1/logistics/tracking/{no}`

Notes:
- Write endpoints require `Idempotency-Key` and `logistics:write` scope.
- `POST /v1/logistics/shipments` returns `201`, while delivery returns `200`.

## Finance API

- `GET /v1/finance/receivables`
- `POST /v1/finance/receivables`
- `POST /v1/finance/receivables/{receivable_id}/payments`
- `POST /v1/finance/receivables/{receivable_id}/refunds`
- `GET /v1/finance/invoices`
- `GET /v1/finance/statements`

Notes:
- Write endpoints require `Idempotency-Key` and `finance:write` scope.
- Payment recording supports partial settlement; overpayment is rejected with `409`.
- Refund recording is supported on the same receivable resource; over-refund is rejected with `409`.

## Workspace API

- `POST /v1/workspace/auth/login`
- `GET /v1/workspace/me`
- `GET /v1/workspace/bootstrap`
- `GET /v1/workspace/customers`
- `POST /v1/workspace/customers`
- `PATCH /v1/workspace/customers/{customer_id}`
- `GET /v1/workspace/orders`
- `POST /v1/workspace/orders`
- `PUT /v1/workspace/orders/{order_id}`
- `POST /v1/workspace/orders/{order_id}/entered`
- `POST /v1/workspace/orders/{order_id}/steps/{step_key}`
- `POST /v1/workspace/orders/{order_id}/pickup/approve`
- `POST /v1/workspace/orders/{order_id}/pickup/send-email`
- `POST /v1/workspace/orders/{order_id}/pickup/signature`
- `GET /v1/workspace/shipments`
- `POST /v1/workspace/orders/{order_id}/shipment`
- `POST /v1/workspace/shipments/{shipment_id}/deliver`
- `GET /v1/workspace/receivables`
- `POST /v1/workspace/orders/{order_id}/receivable`
- `POST /v1/workspace/receivables/{receivable_id}/payments`
- `POST /v1/workspace/receivables/{receivable_id}/refunds`
- `GET /v1/workspace/notifications`
- `POST /v1/workspace/notifications/read`
- `GET /v1/workspace/settings/glass-types`
- `POST /v1/workspace/settings/glass-types`
- `PATCH /v1/workspace/settings/glass-types/{glass_type_id}`
- `GET /v1/workspace/settings/notification-templates/{template_key}`
- `PUT /v1/workspace/settings/notification-templates/{template_key}`
- `GET /v1/workspace/email-logs`

Notes:
- Workspace write endpoints require `Idempotency-Key` and return the standard success envelope.
- `POST /v1/workspace/orders` rejects missing idempotency headers with `400`.
- Workspace finance writes now include refunds, and settings/notification writes are also idempotent formal `/v1/workspace/*` endpoints.

## App API

- `GET /v1/app/bootstrap`
- `GET /v1/app/orders`
- `GET /v1/app/orders/{order_id}`
- `POST /v1/app/orders`
- `GET /v1/app/profile`
- `GET /v1/app/credit`
- `GET /v1/app/notifications`
- `POST /v1/app/notifications/read`

Notes:
- Customer app success responses follow the standard `{ data, request_id, timestamp }` envelope.
- `POST /v1/app/orders` requires `customer` role and `Idempotency-Key`; `customer_viewer` is rejected with `403`, and duplicate writes are rejected with `409`.

## Admin API

- `GET /v1/admin/health/live`
- `GET /v1/admin/health/ready`
- `GET /v1/admin/runtime/probe`
- `GET /v1/admin/runtime/metrics`
- `GET /v1/admin/users`
- `PUT /v1/admin/users/{user_id}`
- `POST /v1/admin/users/bulk`

Notes:
- Admin success responses follow the standard `{ data, request_id, timestamp }` envelope.
- `GET /v1/admin/runtime/probe` requires `admin` or `manager`; disallowed roles return `403` with the standard error envelope.
