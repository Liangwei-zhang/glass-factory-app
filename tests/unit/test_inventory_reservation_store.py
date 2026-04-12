from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from infra.cache import inventory_reservation as reservation_module
from infra.cache.inventory_reservation import (
    CONFIRMED_RESERVATION_TTL_SECONDS,
    RELEASED_RESERVATION_TTL_SECONDS,
    InventoryReservationSnapshot,
    InventoryStockSnapshot,
    RedisInventoryReservationStore,
    reservation_key,
    stock_key,
)
from infra.core.errors import AppError


class FakeRedisPipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.commands: list[tuple] = []

    def exists(self, key: str) -> "FakeRedisPipeline":
        self.commands.append(("exists", key))
        return self

    def hget(self, key: str, field: str) -> "FakeRedisPipeline":
        self.commands.append(("hget", key, field))
        return self

    def hset(self, key: str, *, mapping: dict[str, object]) -> "FakeRedisPipeline":
        self.commands.append(("hset", key, mapping))
        return self

    def expire(self, key: str, seconds: int) -> "FakeRedisPipeline":
        self.commands.append(("expire", key, seconds))
        return self

    async def execute(self) -> list[object]:
        results: list[object] = []
        for command in self.commands:
            operation = command[0]
            if operation == "exists":
                results.append(await self.redis.exists(command[1]))
            elif operation == "hget":
                results.append(await self.redis.hget(command[1], command[2]))
            elif operation == "hset":
                results.append(await self.redis.hset(command[1], mapping=command[2]))
            elif operation == "expire":
                results.append(await self.redis.expire(command[1], command[2]))
        self.commands.clear()
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, *, transaction: bool = False) -> FakeRedisPipeline:
        _ = transaction
        return FakeRedisPipeline(self)

    async def exists(self, key: str) -> int:
        return 1 if key in self.hashes else 0

    async def hset(self, key: str, *, mapping: dict[str, object]) -> int:
        target = self.hashes.setdefault(key, {})
        for field, value in mapping.items():
            target[str(field)] = str(value)
        return len(mapping)

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.hashes:
            return False
        self.ttls[key] = int(seconds)
        return True

    async def persist(self, key: str) -> bool:
        if key not in self.hashes:
            return False
        self.ttls.pop(key, None)
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.hashes:
                removed += 1
                del self.hashes[key]
            self.ttls.pop(key, None)
        return removed

    async def eval(self, script: str, numkeys: int, *values: object) -> list[str]:
        keys = [str(value) for value in values[:numkeys]]
        args = [str(value) for value in values[numkeys:]]

        if script == reservation_module.RESERVE_STOCK_LUA:
            return self._eval_reserve(keys, args)
        if script == reservation_module.CONFIRM_STOCK_LUA:
            return self._eval_confirm(keys, args)
        if script == reservation_module.RELEASE_STOCK_LUA:
            return self._eval_release(keys, args)
        raise NotImplementedError("Unexpected Lua script")

    def _eval_reserve(self, keys: list[str], args: list[str]) -> list[str]:
        item_count = int(args[0])
        ttl_seconds = int(args[1])
        now_iso = args[2]
        expires_at_iso = args[3]
        order_no = args[4]
        quantities = [int(value) for value in args[5 : 5 + item_count]]
        product_ids = args[5 + item_count : 5 + (2 * item_count)]
        reservation_ids = args[5 + (2 * item_count) : 5 + (3 * item_count)]

        insufficient: list[str] = []
        for index, stock in enumerate(keys[:item_count]):
            available_qty = self._read_int(stock, "available_qty")
            required_qty = quantities[index]
            if available_qty < required_qty:
                insufficient.extend(
                    [
                        product_ids[index],
                        str(available_qty),
                        str(required_qty),
                    ]
                )

        if insufficient:
            return ["insufficient", *insufficient]

        for index, stock in enumerate(keys[:item_count]):
            reservation = keys[item_count + index]
            required_qty = quantities[index]
            available_qty = self._read_int(stock, "available_qty") - required_qty
            reserved_qty = self._read_int(stock, "reserved_qty") + required_qty
            self.hashes[stock].update(
                {
                    "available_qty": str(available_qty),
                    "reserved_qty": str(reserved_qty),
                    "total_qty": str(available_qty + reserved_qty),
                    "updated_at": now_iso,
                }
            )
            self.hashes[reservation] = {
                "reservation_id": reservation_ids[index],
                "product_id": product_ids[index],
                "quantity": str(required_qty),
                "order_no": order_no,
                "status": "pending",
                "created_at": now_iso,
                "expires_at": expires_at_iso,
            }
            self.ttls[reservation] = ttl_seconds

        return ["ok"]

    def _eval_confirm(self, keys: list[str], args: list[str]) -> list[str]:
        item_count = int(args[0])
        now_iso = args[1]
        ttl_seconds = int(args[2])
        quantities = [int(value) for value in args[3 : 3 + item_count]]
        reservation_ids = args[3 + item_count : 3 + (2 * item_count)]

        for index, reservation in enumerate(keys[item_count:]):
            status = self.hashes.get(reservation, {}).get("status")
            if status is None:
                return ["missing", reservation_ids[index]]
            if status not in {"pending", "confirmed"}:
                return ["invalid", reservation_ids[index], status]

        changed = 0
        for index, reservation in enumerate(keys[item_count:]):
            stock = keys[index]
            status = self.hashes[reservation]["status"]
            if status != "pending":
                continue

            available_qty = self._read_int(stock, "available_qty")
            reserved_qty = self._read_int(stock, "reserved_qty") - quantities[index]
            self.hashes[stock].update(
                {
                    "reserved_qty": str(reserved_qty),
                    "total_qty": str(available_qty + reserved_qty),
                    "updated_at": now_iso,
                }
            )
            self.hashes[reservation].update(
                {
                    "status": "confirmed",
                    "confirmed_at": now_iso,
                }
            )
            if ttl_seconds > 0:
                self.ttls[reservation] = ttl_seconds
            else:
                self.ttls.pop(reservation, None)
            changed += 1

        return ["ok", str(changed)]

    def _eval_release(self, keys: list[str], args: list[str]) -> list[str]:
        item_count = int(args[0])
        now_iso = args[1]
        release_reason = args[2]
        ttl_seconds = int(args[3])
        quantities = [int(value) for value in args[4 : 4 + item_count]]
        reservation_ids = args[4 + item_count : 4 + (2 * item_count)]

        for index, reservation in enumerate(keys[item_count:]):
            status = self.hashes.get(reservation, {}).get("status")
            if status is None:
                return ["missing", reservation_ids[index]]
            if status not in {"pending", "confirmed", "released"}:
                return ["invalid", reservation_ids[index], status]

        changed = 0
        for index, reservation in enumerate(keys[item_count:]):
            stock = keys[index]
            status = self.hashes[reservation]["status"]
            available_qty = self._read_int(stock, "available_qty")
            reserved_qty = self._read_int(stock, "reserved_qty")

            if status == "pending":
                available_qty += quantities[index]
                reserved_qty -= quantities[index]
            elif status == "confirmed":
                available_qty += quantities[index]

            if status != "released":
                self.hashes[stock].update(
                    {
                        "available_qty": str(available_qty),
                        "reserved_qty": str(reserved_qty),
                        "total_qty": str(available_qty + reserved_qty),
                        "updated_at": now_iso,
                    }
                )
                self.hashes[reservation].update(
                    {
                        "status": "released",
                        "released_at": now_iso,
                        "release_reason": release_reason,
                    }
                )
                self.ttls[reservation] = ttl_seconds
                changed += 1

        return ["ok", str(changed)]

    def _read_int(self, key: str, field: str) -> int:
        return int(self.hashes.get(key, {}).get(field, "0"))


def _stock_snapshot(
    *,
    product_id: str = "product-1",
    available_qty: int,
    reserved_qty: int,
    total_qty: int,
    version: int = 1,
) -> InventoryStockSnapshot:
    return InventoryStockSnapshot(
        product_id=product_id,
        available_qty=available_qty,
        reserved_qty=reserved_qty,
        total_qty=total_qty,
        version=version,
    )


def _reservation_snapshot(
    *,
    reservation_id: str = "res-1",
    product_id: str = "product-1",
    quantity: int,
    status: str,
    order_no: str = "GF-1001",
    expires_at: datetime | None = None,
    confirmed_at: datetime | None = None,
    released_at: datetime | None = None,
    release_reason: str | None = None,
) -> InventoryReservationSnapshot:
    return InventoryReservationSnapshot(
        reservation_id=reservation_id,
        product_id=product_id,
        quantity=quantity,
        order_no=order_no,
        status=status,
        expires_at=expires_at,
        confirmed_at=confirmed_at,
        released_at=released_at,
        release_reason=release_reason,
    )


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()

    async def _get_redis() -> FakeRedis:
        return redis

    monkeypatch.setattr(reservation_module, "get_redis", _get_redis)
    return redis


@pytest.mark.asyncio
async def test_reserve_writes_pending_reservation_and_updates_stock(fake_redis: FakeRedis) -> None:
    store = RedisInventoryReservationStore()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    result = await store.reserve(
        stock_snapshots=[_stock_snapshot(available_qty=10, reserved_qty=0, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(quantity=4, status="pending", expires_at=expires_at)
        ],
        ttl_seconds=600,
    )

    assert result == []
    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "6"
    assert fake_redis.hashes[stock_key("product-1")]["reserved_qty"] == "4"
    assert fake_redis.hashes[stock_key("product-1")]["total_qty"] == "10"
    assert fake_redis.hashes[reservation_key("res-1")]["status"] == "pending"
    assert fake_redis.hashes[reservation_key("res-1")]["order_no"] == "GF-1001"
    assert fake_redis.ttls[reservation_key("res-1")] == 600


@pytest.mark.asyncio
async def test_reserve_returns_insufficient_items_without_writing_reservation(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()

    result = await store.reserve(
        stock_snapshots=[_stock_snapshot(available_qty=2, reserved_qty=0, total_qty=2)],
        reservation_snapshots=[
            _reservation_snapshot(
                reservation_id="res-insufficient",
                quantity=5,
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
        ],
        ttl_seconds=600,
    )

    assert len(result) == 1
    assert result[0].product_id == "product-1"
    assert result[0].available_qty == 2
    assert result[0].required_qty == 5
    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "2"
    assert reservation_key("res-insufficient") not in fake_redis.hashes


@pytest.mark.asyncio
async def test_reserve_refreshes_existing_stock_snapshot_when_version_changed(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await fake_redis.hset(
        stock_key("product-1"),
        mapping={
            "product_id": "product-1",
            "available_qty": 0,
            "reserved_qty": 10,
            "total_qty": 10,
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    result = await store.reserve(
        stock_snapshots=[
            _stock_snapshot(available_qty=1000, reserved_qty=0, total_qty=1000, version=2)
        ],
        reservation_snapshots=[
            _reservation_snapshot(
                reservation_id="res-refreshed",
                quantity=4,
                status="pending",
                expires_at=expires_at,
            )
        ],
        ttl_seconds=600,
    )

    assert result == []
    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "996"
    assert fake_redis.hashes[stock_key("product-1")]["reserved_qty"] == "4"
    assert fake_redis.hashes[stock_key("product-1")]["total_qty"] == "1000"
    assert fake_redis.hashes[stock_key("product-1")]["version"] == "2"
    assert fake_redis.hashes[reservation_key("res-refreshed")]["status"] == "pending"


@pytest.mark.asyncio
async def test_confirm_transitions_pending_reservation_and_updates_ttl(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await store.reserve(
        stock_snapshots=[_stock_snapshot(available_qty=10, reserved_qty=0, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(quantity=3, status="pending", expires_at=expires_at)
        ],
        ttl_seconds=600,
    )

    await store.confirm(
        stock_snapshots=[_stock_snapshot(available_qty=7, reserved_qty=3, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(quantity=3, status="pending", expires_at=expires_at)
        ],
    )

    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "7"
    assert fake_redis.hashes[stock_key("product-1")]["reserved_qty"] == "0"
    assert fake_redis.hashes[stock_key("product-1")]["total_qty"] == "7"
    assert fake_redis.hashes[reservation_key("res-1")]["status"] == "confirmed"
    assert fake_redis.hashes[reservation_key("res-1")]["confirmed_at"]
    assert fake_redis.ttls[reservation_key("res-1")] == CONFIRMED_RESERVATION_TTL_SECONDS


@pytest.mark.asyncio
async def test_confirm_raises_when_existing_reservation_status_is_invalid(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()
    released_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    await fake_redis.hset(
        stock_key("product-1"),
        mapping={
            "product_id": "product-1",
            "available_qty": 10,
            "reserved_qty": 0,
            "total_qty": 10,
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await fake_redis.hset(
        reservation_key("res-1"),
        mapping={
            "reservation_id": "res-1",
            "product_id": "product-1",
            "quantity": 2,
            "order_no": "GF-1001",
            "status": "released",
            "released_at": released_at.isoformat(),
            "release_reason": "order_cancelled",
        },
    )

    with pytest.raises(AppError) as exc_info:
        await store.confirm(
            stock_snapshots=[_stock_snapshot(available_qty=10, reserved_qty=0, total_qty=10)],
            reservation_snapshots=[
                _reservation_snapshot(
                    quantity=2,
                    status="released",
                    released_at=released_at,
                    release_reason="order_cancelled",
                )
            ],
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.message == "Inventory reservation is invalid during confirm."
    assert exc_info.value.details == {
        "reservation_id": "res-1",
        "status": "released",
        "operation": "confirm",
    }


@pytest.mark.asyncio
async def test_release_restores_available_qty_for_confirmed_reservation(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await store.reserve(
        stock_snapshots=[_stock_snapshot(available_qty=10, reserved_qty=0, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(quantity=3, status="pending", expires_at=expires_at)
        ],
        ttl_seconds=600,
    )
    await store.confirm(
        stock_snapshots=[_stock_snapshot(available_qty=7, reserved_qty=3, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(quantity=3, status="pending", expires_at=expires_at)
        ],
    )

    await store.release(
        stock_snapshots=[_stock_snapshot(available_qty=7, reserved_qty=0, total_qty=7)],
        reservation_snapshots=[
            _reservation_snapshot(
                quantity=3,
                status="confirmed",
                expires_at=expires_at,
                confirmed_at=datetime.now(timezone.utc),
            )
        ],
        release_reason="order_cancelled",
    )

    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "10"
    assert fake_redis.hashes[stock_key("product-1")]["reserved_qty"] == "0"
    assert fake_redis.hashes[stock_key("product-1")]["total_qty"] == "10"
    assert fake_redis.hashes[reservation_key("res-1")]["status"] == "released"
    assert fake_redis.hashes[reservation_key("res-1")]["release_reason"] == "order_cancelled"
    assert fake_redis.ttls[reservation_key("res-1")] == RELEASED_RESERVATION_TTL_SECONDS


@pytest.mark.asyncio
async def test_restore_state_overwrites_snapshots_and_deletes_reservations(
    fake_redis: FakeRedis,
) -> None:
    store = RedisInventoryReservationStore()
    delete_key = reservation_key("res-delete")
    await fake_redis.hset(delete_key, mapping={"status": "pending"})

    await store.restore_state(
        stock_snapshots=[_stock_snapshot(available_qty=9, reserved_qty=1, total_qty=10)],
        reservation_snapshots=[
            _reservation_snapshot(
                quantity=1,
                status="confirmed",
                confirmed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        ],
        delete_reservation_ids=["res-delete"],
    )

    assert fake_redis.hashes[stock_key("product-1")]["available_qty"] == "9"
    assert fake_redis.hashes[stock_key("product-1")]["reserved_qty"] == "1"
    assert fake_redis.hashes[reservation_key("res-1")]["status"] == "confirmed"
    assert fake_redis.ttls[reservation_key("res-1")] == CONFIRMED_RESERVATION_TTL_SECONDS
    assert delete_key not in fake_redis.hashes
