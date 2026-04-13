from __future__ import annotations

from types import SimpleNamespace

import pytest

from domains.workspace import orders_support
from infra.core.errors import AppError


def test_order_matches_filters_uses_customer_contact_fields() -> None:
    order = {
        "orderNo": "GF-001",
        "status": "received",
        "priority": "rush",
        "customer": {
            "companyName": "Acme Glass",
            "phone": "13800138000",
            "email": "ops@acme.test",
        },
    }

    assert orders_support.order_matches_filters(order, query="acme") is True
    assert orders_support.order_matches_filters(order, query="1380013") is True
    assert orders_support.order_matches_filters(order, status="received") is True
    assert orders_support.order_matches_filters(order, priority="rush") is True
    assert orders_support.order_matches_filters(order, query="missing") is False
    assert orders_support.order_matches_filters(order, status="completed") is False


def test_normalize_piece_numbers_keeps_only_numeric_entries() -> None:
    assert orders_support.normalize_piece_numbers([1, "2", "x", None, "03"]) == [1, 2, 3]


def test_parse_workspace_items_json_supports_multiple_rows() -> None:
    rows = orders_support._parse_workspace_order_item_rows(
        items_json=(
            '[{"glassType":"RAIN","thickness":"8mm","quantity":2,'
            '"widthMm":1200,"heightMm":800},'
            '{"glass_type":"FROSTED","specification":"6mm","quantity":1}]'
        ),
        glass_type=None,
        thickness=None,
        quantity=None,
        special_instructions="priority hold",
    )

    assert rows == [
        {
            "glass_type": "RAIN",
            "specification": "8mm",
            "quantity": 2,
            "width_mm": 1200,
            "height_mm": 800,
            "process_requirements": "priority hold",
        },
        {
            "glass_type": "FROSTED",
            "specification": "6mm",
            "quantity": 1,
            "width_mm": 1000,
            "height_mm": 1000,
            "process_requirements": "priority hold",
        },
    ]


def test_parse_workspace_items_json_rejects_empty_rows() -> None:
    with pytest.raises(AppError) as exc:
        orders_support._parse_workspace_order_item_rows(
            items_json="[]",
            glass_type=None,
            thickness=None,
            quantity=None,
            special_instructions="",
        )

    assert exc.value.message == "itemsJson 至少要包含一条明细。"
    assert exc.value.status_code == 400


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _FakeScalarResult(self._rows)


@pytest.mark.asyncio
async def test_list_workspace_orders_filters_batch_serialized_payloads(monkeypatch) -> None:
    rows = [SimpleNamespace(id="order-1"), SimpleNamespace(id="order-2")]
    session = _FakeSession(rows)

    async def fake_serialize_orders(
        _session, orders, *, include_detail: bool = False, route_prefix: str = "/api"
    ):
        assert orders == rows
        assert include_detail is False
        assert route_prefix == "/v1/workspace"
        return [
            {
                "orderNo": "GF-001",
                "status": "received",
                "priority": "rush",
                "customer": {
                    "companyName": "Acme Glass",
                    "phone": "13800138000",
                    "email": "ops@acme.test",
                },
            },
            {
                "orderNo": "GF-002",
                "status": "completed",
                "priority": "normal",
                "customer": {
                    "companyName": "Other Glass",
                    "phone": "13900139000",
                    "email": "hello@other.test",
                },
            },
        ]

    monkeypatch.setattr(orders_support.ui_support, "serialize_orders", fake_serialize_orders)

    payloads = await orders_support.list_workspace_orders(
        session,
        query="acme",
        status="received",
        priority="rush",
    )

    assert payloads == [
        {
            "orderNo": "GF-001",
            "status": "received",
            "priority": "rush",
            "customer": {
                "companyName": "Acme Glass",
                "phone": "13800138000",
                "email": "ops@acme.test",
            },
        }
    ]
