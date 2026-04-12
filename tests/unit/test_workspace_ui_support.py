from __future__ import annotations

from datetime import timezone

import pytest

from domains.workspace import ui_support
from infra.db.models.inventory import InventoryModel, ProductModel


class _FakeScalarResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, *, product: ProductModel | None, inventory: InventoryModel | None) -> None:
        self.product = product
        self.inventory = inventory
        self.added: list[object] = []

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is ProductModel:
            return _FakeScalarResult(self.product)
        if entity is InventoryModel:
            return _FakeScalarResult(self.inventory)
        raise AssertionError(f"Unexpected statement: {statement}")

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, ProductModel):
            if obj.id is None:
                obj.id = "product-1"
            self.product = obj
            return
        if isinstance(obj, InventoryModel):
            self.inventory = obj

    async def flush(self) -> None:
        return None


def test_parse_date_input_supports_iso_date_and_fallback() -> None:
    parsed = ui_support.parse_date_input("2026-04-10")

    assert parsed.year == 2026
    assert parsed.month == 4
    assert parsed.day == 10
    assert parsed.tzinfo == timezone.utc

    fallback = ui_support.parse_date_input(None)

    assert fallback.tzinfo == timezone.utc


def test_order_ui_helpers_preserve_status_and_piece_labels() -> None:
    assert ui_support.to_ui_status("pending") == "received"
    assert ui_support.to_ui_status("ready_for_pickup") == "ready_for_pickup"
    assert ui_support.to_ui_status("shipping") == "shipping"
    assert ui_support.to_ui_status("delivered") == "delivered"
    assert ui_support.status_label("completed") == "已完成"
    assert ui_support.status_label("shipping") == "配送中"
    assert ui_support.priority_label("rush") == "加急"
    assert ui_support.step_status_label("in_progress") == "进行中"
    assert ui_support.format_piece_summary([3, 1, 3, 2]) == "第 1 片、第 2 片、第 3 片"


def test_build_order_asset_url_uses_explicit_route_prefix() -> None:
    assert ui_support.build_order_asset_url("/v1/workspace", "order-1", "drawing") == (
        "/v1/workspace/orders/order-1/drawing"
    )
    assert ui_support.build_order_asset_url("/v1/app/", "order-2", "/drawing") == (
        "/v1/app/orders/order-2/drawing"
    )


@pytest.mark.asyncio
async def test_ensure_product_inventory_creates_large_synthetic_headroom() -> None:
    session = _FakeSession(product=None, inventory=None)

    product = await ui_support.ensure_product_inventory(session, "Tempered", "6mm", 1)

    assert product.product_code == "GLASS-TEMPERED-6MM"
    assert session.inventory is not None
    assert session.inventory.available_qty == ui_support.AUTO_STOCK_TARGET_AVAILABLE_QTY
    assert session.inventory.total_qty == ui_support.AUTO_STOCK_TARGET_AVAILABLE_QTY
    assert session.inventory.safety_stock == 20


@pytest.mark.asyncio
async def test_ensure_product_inventory_refills_when_available_drops_below_threshold() -> None:
    product = ProductModel(
        id="product-1",
        product_code="GLASS-TEMPERED-6MM",
        product_name="Tempered 6mm",
        glass_type="Tempered",
        specification="6mm",
        is_active=True,
    )
    inventory = InventoryModel(
        product_id="product-1",
        available_qty=12,
        reserved_qty=8,
        total_qty=20,
        safety_stock=20,
        warehouse_code="WH01",
        version=4,
    )
    session = _FakeSession(product=product, inventory=inventory)

    returned = await ui_support.ensure_product_inventory(session, "Tempered", "6mm", 1)

    assert returned is product
    assert inventory.available_qty == ui_support.AUTO_STOCK_TARGET_AVAILABLE_QTY
    assert inventory.total_qty == ui_support.AUTO_STOCK_TARGET_AVAILABLE_QTY + 8
    assert inventory.version == 5
