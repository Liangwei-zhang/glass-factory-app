from __future__ import annotations

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


class InventoryService:
    def __init__(self, repository: InventoryRepository | None = None) -> None:
        self.repository = repository or InventoryRepository()

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
        reservation_ids: list[str] = []
        insufficient_items: list[InsufficientInventoryItem] = []

        for item in request.items:
            stock = await self.repository.get_inventory_for_update(session, item.product_id)
            available_qty = stock.available_qty if stock else 0

            if stock is None or available_qty < item.quantity:
                insufficient_items.append(
                    InsufficientInventoryItem(
                        product_id=item.product_id,
                        required_qty=item.quantity,
                        available_qty=available_qty,
                    )
                )
                continue

            stock.available_qty -= item.quantity
            stock.reserved_qty += item.quantity
            stock.total_qty = stock.available_qty + stock.reserved_qty
            stock.version += 1

            reservation_ids.append(f"rsv-{request.order_no}-{uuid4().hex[:10]}")

        return InventoryReservationResult(
            reservation_ids=reservation_ids,
            insufficient_items=insufficient_items,
        )

    async def get_inventory_item(self, session: AsyncSession, product_id: str) -> InventorySnapshot:
        row = await self.repository.get_inventory(session, product_id)
        if row is None:
            raise inventory_not_found(product_id)
        return InventorySnapshot.model_validate(row)
