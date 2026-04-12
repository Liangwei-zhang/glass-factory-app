# Cache Strategy Matrix

This file is the merge checklist for read paths. If a new read surface is not represented here, its cache policy is not defined yet.

| Surface | Cache key | TTL | Fill / refresh trigger | Invalidation trigger | Current state |
| --- | --- | --- | --- | --- | --- |
| Order aggregate / order detail | `cache:order:{order_id}` | `30s` | Read miss fill once the helper is wired into the formal read path | Order create, update, cancel, production progression, pickup, shipment, finance side effects touching rendered order state | Helper exists in `infra/cache/order_cache.py`; main-path read integration still pending |
| Customer aggregate / profile | `cache:customer:{customer_id}` | `60s` | Read miss fill once the helper is wired into customer/profile reads | Customer update, credit-affecting writes, identity-binding changes that alter rendered customer payload | Helper exists in `infra/cache/customer_cache.py`; main-path read integration still pending |
| Inventory snapshot | `cache:inventory:{product_id}` | `60s` | Read miss fill or post-sync refresh when formal inventory reads start using the cache | Reservation create/confirm/release/restore, stock adjustment, sync replay | Helper exists in `infra/cache/inventory_cache.py`; read-path integration and replay policy still pending |

## Rule

- Every new read path must add a row before merge.
- If the route is intentionally uncached, write `no cache` in the cache-key column and explain the fallback in the current-state column.
- TTL, refresh, and invalidation decisions must be updated together with the route, not as a follow-up cleanup.