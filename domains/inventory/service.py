from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory.errors import inventory_not_found
from domains.inventory.repository import InventoryRepository
from domains.inventory.schema import (
    InsufficientInventoryItem,
    InventoryReservationRequest,
    InventoryReservationResult,
    InventorySnapshot,
)
from infra.cache.inventory_reservation import (
    PENDING_RESERVATION_TTL_SECONDS,
    InventoryReservationSnapshot,
    InventoryStockSnapshot,
    RedisInventoryReservationStore,
)
from infra.core.errors import AppError, ErrorCode
from infra.core.hooks import register_after_rollback_hook
from infra.db.models.inventory import InventoryReservationModel
from infra.events.outbox import OutboxPublisher
from infra.events.topics import Topics


def _stock_snapshot(row) -> InventoryStockSnapshot:
    return InventoryStockSnapshot(
        product_id=row.product_id,
        available_qty=row.available_qty,
        reserved_qty=row.reserved_qty,
        total_qty=row.total_qty,
        version=row.version,
    )


def _reservation_snapshot(row: InventoryReservationModel) -> InventoryReservationSnapshot:
    return InventoryReservationSnapshot(
        reservation_id=row.id,
        product_id=row.product_id,
        quantity=row.reserved_qty,
        order_no=row.order_no,
        status=row.status,
        expires_at=row.expires_at,
        confirmed_at=row.confirmed_at,
        released_at=row.released_at,
        release_reason=row.release_reason,
    )


class InventoryService:
    def __init__(
        self,
        repository: InventoryRepository | None = None,
        reservation_store: RedisInventoryReservationStore | None = None,
        reservation_ttl_seconds: int = PENDING_RESERVATION_TTL_SECONDS,
    ) -> None:
        self.repository = repository or InventoryRepository()
        self.reservation_store = reservation_store or RedisInventoryReservationStore()
        self.reservation_ttl_seconds = reservation_ttl_seconds

    async def list_inventory(
        self,
        session: AsyncSession,
        product_ids: list[str] | None = None,
    ) -> list[InventorySnapshot]:
        rows = await self.repository.list_inventory(session, product_ids=product_ids)
        return [InventorySnapshot.model_validate(row) for row in rows]

    async def reserve_stock(
        self,
        session: AsyncSession,
        request: InventoryReservationRequest,
    ) -> InventoryReservationResult:
        if not request.items:
            return InventoryReservationResult()

        requested_quantities: dict[str, int] = defaultdict(int)
        for item in request.items:
            requested_quantities[item.product_id] += item.quantity

        inventory_rows = await self.repository.list_inventory_for_update(
            session,
            product_ids=sorted(requested_quantities),
        )
        inventory_by_product_id = {row.product_id: row for row in inventory_rows}

        insufficient_items: list[InsufficientInventoryItem] = []
        for product_id, quantity in requested_quantities.items():
            row = inventory_by_product_id.get(product_id)
            if row is not None:
                continue
            insufficient_items.append(
                InsufficientInventoryItem(
                    product_id=product_id,
                    required_qty=quantity,
                    available_qty=0,
                )
            )

        if insufficient_items:
            return InventoryReservationResult(insufficient_items=insufficient_items)

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.ttl_seconds)
        stock_snapshots = [_stock_snapshot(row) for row in inventory_rows]
        reservation_snapshots = [
            InventoryReservationSnapshot(
                reservation_id=f"rsv-{request.order_no}-{uuid4().hex[:10]}",
                product_id=product_id,
                quantity=quantity,
                order_no=request.order_no,
                status="pending",
                expires_at=expires_at,
            )
            for product_id, quantity in sorted(requested_quantities.items())
        ]

        insufficient_items = await self.reservation_store.reserve(
            stock_snapshots=stock_snapshots,
            reservation_snapshots=reservation_snapshots,
            ttl_seconds=request.ttl_seconds,
        )
        if insufficient_items:
            return InventoryReservationResult(insufficient_items=insufficient_items)

        for snapshot in reservation_snapshots:
            stock = inventory_by_product_id[snapshot.product_id]
            stock.available_qty -= snapshot.quantity
            stock.reserved_qty += snapshot.quantity
            stock.total_qty = stock.available_qty + stock.reserved_qty
            stock.version += 1

            session.add(
                InventoryReservationModel(
                    id=snapshot.reservation_id,
                    product_id=snapshot.product_id,
                    order_no=snapshot.order_no,
                    reserved_qty=snapshot.quantity,
                    status=snapshot.status,
                    expires_at=snapshot.expires_at,
                )
            )

        register_after_rollback_hook(
            session,
            self._build_restore_hook(
                stock_snapshots=stock_snapshots,
                reservation_snapshots=[],
                delete_reservation_ids=[
                    snapshot.reservation_id for snapshot in reservation_snapshots
                ],
            ),
        )

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.INVENTORY_RESERVED,
            key=request.order_no,
            payload={
                "order_no": request.order_no,
                "reservation_ids": [snapshot.reservation_id for snapshot in reservation_snapshots],
                "items": [
                    {
                        "product_id": snapshot.product_id,
                        "reserved_qty": snapshot.quantity,
                    }
                    for snapshot in reservation_snapshots
                ],
                "expires_at": expires_at.isoformat(),
            },
        )

        return InventoryReservationResult(
            reservation_ids=[snapshot.reservation_id for snapshot in reservation_snapshots],
            expires_at=expires_at,
        )

    async def confirm_stock(
        self,
        session: AsyncSession,
        reservation_ids: list[str],
        *,
        order_id: str | None = None,
    ) -> int:
        rows = await self.repository.list_reservations(session, reservation_ids, for_update=True)
        if not rows:
            return 0

        missing_ids = sorted(set(reservation_ids) - {row.id for row in rows})
        if missing_ids:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Inventory reservation does not exist.",
                status_code=409,
                details={"reservation_ids": missing_ids},
            )

        invalid_rows = [row.id for row in rows if row.status not in {"pending", "confirmed"}]
        if invalid_rows:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Inventory reservation cannot be confirmed from current status.",
                status_code=409,
                details={"reservation_ids": invalid_rows},
            )

        inventory_rows = await self.repository.list_inventory_for_update(
            session,
            product_ids=sorted({row.product_id for row in rows}),
        )
        inventory_by_product_id = {row.product_id: row for row in inventory_rows}
        stock_snapshots = [_stock_snapshot(row) for row in inventory_rows]
        reservation_snapshots = [_reservation_snapshot(row) for row in rows]

        await self.reservation_store.confirm(
            stock_snapshots=stock_snapshots,
            reservation_snapshots=reservation_snapshots,
        )

        now = datetime.now(timezone.utc)
        deducted_by_product: dict[str, int] = defaultdict(int)
        changed_rows: list[InventoryReservationModel] = []

        for row in rows:
            if order_id and row.order_id is None:
                row.order_id = order_id
            if row.status != "pending":
                continue
            row.status = "confirmed"
            row.confirmed_at = now
            deducted_by_product[row.product_id] += row.reserved_qty
            changed_rows.append(row)

        for product_id, quantity in deducted_by_product.items():
            stock = inventory_by_product_id[product_id]
            stock.reserved_qty -= quantity
            stock.total_qty = stock.available_qty + stock.reserved_qty
            stock.version += 1

        if not changed_rows:
            return 0

        register_after_rollback_hook(
            session,
            self._build_restore_hook(
                stock_snapshots=stock_snapshots,
                reservation_snapshots=reservation_snapshots,
            ),
        )

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.INVENTORY_DEDUCTED,
            key=order_id,
            payload={
                "order_id": order_id,
                "reservation_ids": [row.id for row in changed_rows],
                "items": [
                    {"product_id": row.product_id, "deducted_qty": row.reserved_qty}
                    for row in changed_rows
                ],
            },
        )

        return len(changed_rows)

    async def release_stock(
        self,
        session: AsyncSession,
        reservation_ids: list[str],
        *,
        order_id: str | None = None,
        release_reason: str,
    ) -> int:
        rows = await self.repository.list_reservations(session, reservation_ids, for_update=True)
        if not rows:
            return 0

        missing_ids = sorted(set(reservation_ids) - {row.id for row in rows})
        if missing_ids:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Inventory reservation does not exist.",
                status_code=409,
                details={"reservation_ids": missing_ids},
            )

        invalid_rows = [
            row.id for row in rows if row.status not in {"pending", "confirmed", "released"}
        ]
        if invalid_rows:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Inventory reservation cannot be released from current status.",
                status_code=409,
                details={"reservation_ids": invalid_rows},
            )

        inventory_rows = await self.repository.list_inventory_for_update(
            session,
            product_ids=sorted({row.product_id for row in rows}),
        )
        inventory_by_product_id = {row.product_id: row for row in inventory_rows}
        stock_snapshots = [_stock_snapshot(row) for row in inventory_rows]
        reservation_snapshots = [_reservation_snapshot(row) for row in rows]

        await self.reservation_store.release(
            stock_snapshots=stock_snapshots,
            reservation_snapshots=reservation_snapshots,
            release_reason=release_reason,
        )

        now = datetime.now(timezone.utc)
        changed_rows: list[InventoryReservationModel] = []
        for row in rows:
            if order_id and row.order_id is None:
                row.order_id = order_id

            previous_status = row.status
            if previous_status == "pending":
                stock = inventory_by_product_id[row.product_id]
                stock.available_qty += row.reserved_qty
                stock.reserved_qty -= row.reserved_qty
                stock.total_qty = stock.available_qty + stock.reserved_qty
                stock.version += 1
            elif previous_status == "confirmed":
                stock = inventory_by_product_id[row.product_id]
                stock.available_qty += row.reserved_qty
                stock.total_qty = stock.available_qty + stock.reserved_qty
                stock.version += 1
            else:
                continue

            row.status = "released"
            row.released_at = now
            row.release_reason = release_reason
            changed_rows.append(row)

        if not changed_rows:
            return 0

        register_after_rollback_hook(
            session,
            self._build_restore_hook(
                stock_snapshots=stock_snapshots,
                reservation_snapshots=reservation_snapshots,
            ),
        )

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.INVENTORY_ROLLED_BACK,
            key=order_id,
            payload={
                "order_id": order_id,
                "reservation_ids": [row.id for row in changed_rows],
                "reason": release_reason,
                "items": [
                    {"product_id": row.product_id, "released_qty": row.reserved_qty}
                    for row in changed_rows
                ],
            },
        )

        return len(changed_rows)

    async def release_expired_reservations(
        self,
        session: AsyncSession,
        *,
        limit: int = 200,
    ) -> int:
        rows = await self.repository.list_expired_pending_reservations(
            session,
            cutoff=datetime.now(timezone.utc),
            limit=limit,
        )
        if not rows:
            return 0

        return await self.release_stock(
            session,
            [row.id for row in rows],
            release_reason="reservation_expired",
        )

    async def get_inventory_item(self, session: AsyncSession, product_id: str) -> InventorySnapshot:
        row = await self.repository.get_inventory(session, product_id)
        if row is None:
            raise inventory_not_found(product_id)
        return InventorySnapshot.model_validate(row)

    async def adjust_stock(
        self,
        session: AsyncSession,
        *,
        product_id: str,
        direction: str,
        quantity: int,
        actor_user_id: str,
        reason: str = "",
        reference_no: str | None = None,
    ) -> InventorySnapshot:
        normalized_direction = str(direction or "").strip().lower()
        if normalized_direction not in {"in", "out"}:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="direction 必须是 in 或 out。",
                status_code=400,
            )

        if quantity <= 0:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="数量必须大于 0。",
                status_code=400,
            )

        row = await self.repository.get_inventory_for_update(session, product_id)
        if row is None:
            raise inventory_not_found(product_id)

        if normalized_direction == "out" and row.available_qty < quantity:
            raise AppError(
                code=ErrorCode.INVENTORY_SHORTAGE,
                message="库存不足，无法出库。",
                status_code=409,
                details={
                    "product_id": product_id,
                    "available_qty": row.available_qty,
                    "required_qty": quantity,
                },
            )

        row.available_qty = row.available_qty + quantity if normalized_direction == "in" else row.available_qty - quantity
        row.total_qty = row.available_qty + row.reserved_qty
        row.version += 1
        await session.flush()

        outbox = OutboxPublisher(session)
        await outbox.publish_after_commit(
            topic=Topics.OPS_AUDIT_LOGGED,
            key=product_id,
            payload={
                "event": "inventory.manual_adjusted",
                "product_id": product_id,
                "direction": normalized_direction,
                "quantity": quantity,
                "reason": reason.strip(),
                "reference_no": reference_no or "",
                "actor_user_id": actor_user_id,
                "available_qty": row.available_qty,
                "reserved_qty": row.reserved_qty,
                "total_qty": row.total_qty,
            },
        )

        return InventorySnapshot.model_validate(row)

    def _build_restore_hook(
        self,
        *,
        stock_snapshots: list[InventoryStockSnapshot],
        reservation_snapshots: list[InventoryReservationSnapshot],
        delete_reservation_ids: list[str] | None = None,
    ):
        async def rollback_hook(_session: AsyncSession) -> None:
            await self.reservation_store.restore_state(
                stock_snapshots=stock_snapshots,
                reservation_snapshots=reservation_snapshots,
                delete_reservation_ids=delete_reservation_ids or [],
            )

        return rollback_hook
