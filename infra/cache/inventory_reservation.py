from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from redis.asyncio import Redis

from domains.inventory.schema import InsufficientInventoryItem
from infra.cache.redis_client import get_redis

PENDING_RESERVATION_TTL_SECONDS = 15 * 60
CONFIRMED_RESERVATION_TTL_SECONDS = 7 * 24 * 60 * 60
RELEASED_RESERVATION_TTL_SECONDS = 5 * 60

RESERVE_STOCK_LUA = """
local item_count = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])
local now_iso = ARGV[3]
local expires_at_iso = ARGV[4]
local order_no = ARGV[5]
local qty_offset = 5
local product_offset = qty_offset + item_count
local reservation_offset = product_offset + item_count

local insufficient = {}
for i = 1, item_count do
  local stock_key = KEYS[i]
  local required_qty = tonumber(ARGV[qty_offset + i])
  local product_id = ARGV[product_offset + i]
  local available_qty = tonumber(redis.call('HGET', stock_key, 'available_qty') or '0')
  if available_qty < required_qty then
    table.insert(insufficient, product_id)
    table.insert(insufficient, tostring(available_qty))
    table.insert(insufficient, tostring(required_qty))
  end
end

if #insufficient > 0 then
  local response = {'insufficient'}
  for _, value in ipairs(insufficient) do
    table.insert(response, value)
  end
  return response
end

for i = 1, item_count do
  local stock_key = KEYS[i]
  local reservation_key = KEYS[item_count + i]
  local required_qty = tonumber(ARGV[qty_offset + i])
  local product_id = ARGV[product_offset + i]
  local reservation_id = ARGV[reservation_offset + i]

  redis.call('HINCRBY', stock_key, 'available_qty', -required_qty)
  redis.call('HINCRBY', stock_key, 'reserved_qty', required_qty)

  local available_qty = tonumber(redis.call('HGET', stock_key, 'available_qty') or '0')
  local reserved_qty = tonumber(redis.call('HGET', stock_key, 'reserved_qty') or '0')
  redis.call('HSET', stock_key,
    'total_qty', tostring(available_qty + reserved_qty),
    'updated_at', now_iso
  )

  redis.call('HSET', reservation_key,
    'reservation_id', reservation_id,
    'product_id', product_id,
    'quantity', tostring(required_qty),
    'order_no', order_no,
    'status', 'pending',
    'created_at', now_iso,
    'expires_at', expires_at_iso
  )
  redis.call('EXPIRE', reservation_key, ttl_seconds)
end

return {'ok'}
"""

CONFIRM_STOCK_LUA = """
local item_count = tonumber(ARGV[1])
local now_iso = ARGV[2]
local confirm_ttl_seconds = tonumber(ARGV[3])
local qty_offset = 3
local reservation_offset = qty_offset + item_count
local changed = 0

for i = 1, item_count do
  local reservation_key = KEYS[item_count + i]
  local reservation_id = ARGV[reservation_offset + i]
  local status = redis.call('HGET', reservation_key, 'status')
  if not status then
    return {'missing', reservation_id}
  end
  if status ~= 'pending' and status ~= 'confirmed' then
    return {'invalid', reservation_id, status}
  end
end

for i = 1, item_count do
  local stock_key = KEYS[i]
  local reservation_key = KEYS[item_count + i]
  local required_qty = tonumber(ARGV[qty_offset + i])
  local status = redis.call('HGET', reservation_key, 'status')

  if status == 'pending' then
    redis.call('HINCRBY', stock_key, 'reserved_qty', -required_qty)
    local available_qty = tonumber(redis.call('HGET', stock_key, 'available_qty') or '0')
    local reserved_qty = tonumber(redis.call('HGET', stock_key, 'reserved_qty') or '0')
    redis.call('HSET', stock_key,
      'total_qty', tostring(available_qty + reserved_qty),
      'updated_at', now_iso
    )
    redis.call('HSET', reservation_key,
      'status', 'confirmed',
      'confirmed_at', now_iso
    )
    if confirm_ttl_seconds > 0 then
      redis.call('EXPIRE', reservation_key, confirm_ttl_seconds)
    else
      redis.call('PERSIST', reservation_key)
    end
    changed = changed + 1
  end
end

return {'ok', tostring(changed)}
"""

RELEASE_STOCK_LUA = """
local item_count = tonumber(ARGV[1])
local now_iso = ARGV[2]
local release_reason = ARGV[3]
local released_ttl_seconds = tonumber(ARGV[4])
local qty_offset = 4
local reservation_offset = qty_offset + item_count
local changed = 0

for i = 1, item_count do
  local reservation_key = KEYS[item_count + i]
  local reservation_id = ARGV[reservation_offset + i]
  local status = redis.call('HGET', reservation_key, 'status')
  if not status then
    return {'missing', reservation_id}
  end
  if status ~= 'pending' and status ~= 'confirmed' and status ~= 'released' then
    return {'invalid', reservation_id, status}
  end
end

for i = 1, item_count do
  local stock_key = KEYS[i]
  local reservation_key = KEYS[item_count + i]
  local required_qty = tonumber(ARGV[qty_offset + i])
  local status = redis.call('HGET', reservation_key, 'status')

  if status == 'pending' then
    redis.call('HINCRBY', stock_key, 'available_qty', required_qty)
    redis.call('HINCRBY', stock_key, 'reserved_qty', -required_qty)
  elseif status == 'confirmed' then
    redis.call('HINCRBY', stock_key, 'available_qty', required_qty)
  end

  if status ~= 'released' then
    local available_qty = tonumber(redis.call('HGET', stock_key, 'available_qty') or '0')
    local reserved_qty = tonumber(redis.call('HGET', stock_key, 'reserved_qty') or '0')
    redis.call('HSET', stock_key,
      'total_qty', tostring(available_qty + reserved_qty),
      'updated_at', now_iso
    )
    redis.call('HSET', reservation_key,
      'status', 'released',
      'released_at', now_iso,
      'release_reason', release_reason
    )
    if released_ttl_seconds > 0 then
      redis.call('EXPIRE', reservation_key, released_ttl_seconds)
    end
    changed = changed + 1
  end
end

return {'ok', tostring(changed)}
"""


@dataclass(slots=True, frozen=True)
class InventoryStockSnapshot:
    product_id: str
    available_qty: int
    reserved_qty: int
    total_qty: int
    version: int


@dataclass(slots=True, frozen=True)
class InventoryReservationSnapshot:
    reservation_id: str
    product_id: str
    quantity: int
    order_no: str
    status: str
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    released_at: datetime | None = None
    release_reason: str | None = None


def stock_key(product_id: str) -> str:
    return f"inventory:stock:{product_id}"


def reservation_key(reservation_id: str) -> str:
    return f"inventory:reservation:{reservation_id}"


def _isoformat(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat()


def _pending_ttl_seconds(expires_at: datetime | None) -> int:
    if expires_at is None:
        return PENDING_RESERVATION_TTL_SECONDS
    remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    return max(1, remaining)


class RedisInventoryReservationStore:
    async def reserve(
        self,
        *,
        stock_snapshots: list[InventoryStockSnapshot],
        reservation_snapshots: list[InventoryReservationSnapshot],
        ttl_seconds: int,
    ) -> list[InsufficientInventoryItem]:
        if not stock_snapshots:
            return []

        redis = await get_redis()
        await self._ensure_stock_snapshots(redis, stock_snapshots)

        now = datetime.now(timezone.utc)
        expires_at = reservation_snapshots[0].expires_at if reservation_snapshots else None
        keys = [stock_key(snapshot.product_id) for snapshot in stock_snapshots]
        keys.extend(reservation_key(snapshot.reservation_id) for snapshot in reservation_snapshots)
        args: list[str | int] = [
            len(stock_snapshots),
            ttl_seconds,
            now.isoformat(),
            _isoformat(expires_at),
            reservation_snapshots[0].order_no if reservation_snapshots else "",
        ]
        args.extend(snapshot.quantity for snapshot in reservation_snapshots)
        args.extend(snapshot.product_id for snapshot in reservation_snapshots)
        args.extend(snapshot.reservation_id for snapshot in reservation_snapshots)

        raw_result = await redis.eval(RESERVE_STOCK_LUA, len(keys), *keys, *args)
        result = [str(value) for value in raw_result]
        if not result or result[0] == "ok":
            return []

        insufficient_items: list[InsufficientInventoryItem] = []
        if result[0] == "insufficient":
            for index in range(1, len(result), 3):
                insufficient_items.append(
                    InsufficientInventoryItem(
                        product_id=result[index],
                        available_qty=int(result[index + 1]),
                        required_qty=int(result[index + 2]),
                    )
                )
        return insufficient_items

    async def confirm(
        self,
        *,
        stock_snapshots: list[InventoryStockSnapshot],
        reservation_snapshots: list[InventoryReservationSnapshot],
    ) -> None:
        if not reservation_snapshots:
            return

        redis = await get_redis()
        await self._ensure_stock_snapshots(redis, stock_snapshots)
        await self._ensure_reservation_snapshots(redis, reservation_snapshots)

        keys = [stock_key(snapshot.product_id) for snapshot in reservation_snapshots]
        keys.extend(reservation_key(snapshot.reservation_id) for snapshot in reservation_snapshots)
        args: list[str | int] = [
            len(reservation_snapshots),
            datetime.now(timezone.utc).isoformat(),
            CONFIRMED_RESERVATION_TTL_SECONDS,
        ]
        args.extend(snapshot.quantity for snapshot in reservation_snapshots)
        args.extend(snapshot.reservation_id for snapshot in reservation_snapshots)

        raw_result = await redis.eval(CONFIRM_STOCK_LUA, len(keys), *keys, *args)
        self._raise_if_invalid_result([str(value) for value in raw_result], operation="confirm")

    async def release(
        self,
        *,
        stock_snapshots: list[InventoryStockSnapshot],
        reservation_snapshots: list[InventoryReservationSnapshot],
        release_reason: str,
    ) -> None:
        if not reservation_snapshots:
            return

        redis = await get_redis()
        await self._ensure_stock_snapshots(redis, stock_snapshots)
        await self._ensure_reservation_snapshots(redis, reservation_snapshots)

        keys = [stock_key(snapshot.product_id) for snapshot in reservation_snapshots]
        keys.extend(reservation_key(snapshot.reservation_id) for snapshot in reservation_snapshots)
        args: list[str | int] = [
            len(reservation_snapshots),
            datetime.now(timezone.utc).isoformat(),
            release_reason,
            RELEASED_RESERVATION_TTL_SECONDS,
        ]
        args.extend(snapshot.quantity for snapshot in reservation_snapshots)
        args.extend(snapshot.reservation_id for snapshot in reservation_snapshots)

        raw_result = await redis.eval(RELEASE_STOCK_LUA, len(keys), *keys, *args)
        self._raise_if_invalid_result([str(value) for value in raw_result], operation="release")

    async def restore_state(
        self,
        *,
        stock_snapshots: Iterable[InventoryStockSnapshot],
        reservation_snapshots: Iterable[InventoryReservationSnapshot],
        delete_reservation_ids: Iterable[str] = (),
    ) -> None:
        redis = await get_redis()
        await self._force_write_stock_snapshots(redis, list(stock_snapshots))
        await self._force_write_reservation_snapshots(redis, list(reservation_snapshots))

        reservation_ids = list(delete_reservation_ids)
        if reservation_ids:
            await redis.delete(*(reservation_key(reservation_id) for reservation_id in reservation_ids))

    async def _ensure_stock_snapshots(
        self,
        redis: Redis,
        snapshots: list[InventoryStockSnapshot],
    ) -> None:
        if not snapshots:
            return

        keys = [stock_key(snapshot.product_id) for snapshot in snapshots]
        pipeline = redis.pipeline(transaction=False)
        for key in keys:
            pipeline.hget(key, "version")
        version_results = await pipeline.execute()

        pipeline = redis.pipeline(transaction=False)
        touched = False
        for version_value, snapshot in zip(version_results, snapshots, strict=False):
            try:
                cached_version = int(version_value)
            except (TypeError, ValueError):
                cached_version = None

            if cached_version == snapshot.version:
                continue
            touched = True
            pipeline.hset(
                stock_key(snapshot.product_id),
                mapping={
                    "product_id": snapshot.product_id,
                    "available_qty": snapshot.available_qty,
                    "reserved_qty": snapshot.reserved_qty,
                    "total_qty": snapshot.total_qty,
                    "version": snapshot.version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        if touched:
            await pipeline.execute()

    async def _ensure_reservation_snapshots(
        self,
        redis: Redis,
        snapshots: list[InventoryReservationSnapshot],
    ) -> None:
        if not snapshots:
            return

        keys = [reservation_key(snapshot.reservation_id) for snapshot in snapshots]
        pipeline = redis.pipeline(transaction=False)
        for key in keys:
            pipeline.exists(key)
        exists_results = await pipeline.execute()

        pipeline = redis.pipeline(transaction=False)
        touched = False
        for exists_flag, snapshot in zip(exists_results, snapshots, strict=False):
            if exists_flag:
                continue
            touched = True
            self._queue_reservation_snapshot_write(pipeline, snapshot)

        if touched:
            await pipeline.execute()

    async def _force_write_stock_snapshots(
        self,
        redis: Redis,
        snapshots: list[InventoryStockSnapshot],
    ) -> None:
        if not snapshots:
            return

        pipeline = redis.pipeline(transaction=False)
        now_iso = datetime.now(timezone.utc).isoformat()
        for snapshot in snapshots:
            pipeline.hset(
                stock_key(snapshot.product_id),
                mapping={
                    "product_id": snapshot.product_id,
                    "available_qty": snapshot.available_qty,
                    "reserved_qty": snapshot.reserved_qty,
                    "total_qty": snapshot.total_qty,
                    "version": snapshot.version,
                    "updated_at": now_iso,
                },
            )
        await pipeline.execute()

    async def _force_write_reservation_snapshots(
        self,
        redis: Redis,
        snapshots: list[InventoryReservationSnapshot],
    ) -> None:
        if not snapshots:
            return

        pipeline = redis.pipeline(transaction=False)
        for snapshot in snapshots:
            self._queue_reservation_snapshot_write(pipeline, snapshot)
        await pipeline.execute()

    def _queue_reservation_snapshot_write(self, pipeline, snapshot: InventoryReservationSnapshot) -> None:
        key = reservation_key(snapshot.reservation_id)
        pipeline.hset(
            key,
            mapping={
                "reservation_id": snapshot.reservation_id,
                "product_id": snapshot.product_id,
                "quantity": snapshot.quantity,
                "order_no": snapshot.order_no,
                "status": snapshot.status,
                "expires_at": _isoformat(snapshot.expires_at),
                "confirmed_at": _isoformat(snapshot.confirmed_at),
                "released_at": _isoformat(snapshot.released_at),
                "release_reason": snapshot.release_reason or "",
            },
        )

        if snapshot.status == "pending":
            pipeline.expire(key, _pending_ttl_seconds(snapshot.expires_at))
        elif snapshot.status == "confirmed":
            pipeline.expire(key, CONFIRMED_RESERVATION_TTL_SECONDS)
        else:
            pipeline.expire(key, RELEASED_RESERVATION_TTL_SECONDS)

    def _raise_if_invalid_result(self, result: list[str], *, operation: str) -> None:
        from infra.core.errors import AppError, ErrorCode

        if not result or result[0] == "ok":
            return
        if result[0] == "missing":
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Inventory reservation is missing during {operation}.",
                status_code=409,
                details={"reservation_id": result[1], "operation": operation},
            )
        raise AppError(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Inventory reservation is invalid during {operation}.",
            status_code=409,
            details={
                "reservation_id": result[1] if len(result) > 1 else None,
                "status": result[2] if len(result) > 2 else None,
                "operation": operation,
            },
        )