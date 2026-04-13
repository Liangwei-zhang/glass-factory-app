from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from infra.analytics.admin_analytics import AdminAnalyticsWarehouse


class _FakeClickHouseClient:
    async def query_json_rows(self, sql: str):
        if "orders_today" in sql:
            return [
                {
                    "orders_today": 2,
                    "total_orders": 10,
                    "pending_orders": 3,
                    "producing_orders": 2,
                    "completed_orders": 5,
                }
            ]
        if "active_work_orders" in sql:
            return [{"active_work_orders": 4}]
        if "work_order_count" in sql and "GROUP BY status" in sql:
            return [
                {"status": "in_progress", "work_order_count": 2},
                {"status": "pending", "work_order_count": 1},
            ]
        if "FROM production_line_snapshots" in sql:
            return [
                {
                    "id": "line-1",
                    "line_code": "LN-01",
                    "line_name": "Cutting Line",
                    "work_order_count": 3,
                }
            ]
        if "sumIf(total_amount" in sql:
            return [{"orders": 3, "total_sales": "1200.00"}]
        if "GROUP BY status" in sql and "FROM order_snapshots" in sql:
            return [
                {"status": "completed", "order_count": 2},
                {"status": "pending", "order_count": 1},
            ]
        raise AssertionError(f"Unexpected ClickHouse SQL: {sql}")

    async def execute(self, sql: str) -> str:
        raise AssertionError(f"execute should not be called in this unit test: {sql}")


class _Warehouse(AdminAnalyticsWarehouse):
    async def _sync_orders(self, session) -> bool:
        _ = session
        return True

    async def _sync_work_orders(self, session) -> bool:
        _ = session
        return True


@pytest.mark.asyncio
async def test_admin_analytics_warehouse_prefers_clickhouse_for_overview_and_production() -> None:
    warehouse = _Warehouse(client=_FakeClickHouseClient())
    session = SimpleNamespace()

    overview = await warehouse.get_overview(session)
    assert overview["source"] == "clickhouse"
    assert overview["kpis"] == {
        "orders_today": 2,
        "total_orders": 10,
        "pending_orders": 3,
        "producing_orders": 2,
        "completed_orders": 5,
        "active_work_orders": 4,
    }

    production = await warehouse.get_production(session)
    assert production["source"] == "clickhouse"
    assert production["status_breakdown"] == {"in_progress": 2, "pending": 1}
    assert production["lines"] == [
        {
            "line_id": "line-1",
            "line_code": "LN-01",
            "line_name": "Cutting Line",
            "work_order_count": 3,
        }
    ]


@pytest.mark.asyncio
async def test_admin_analytics_warehouse_prefers_clickhouse_for_sales() -> None:
    warehouse = _Warehouse(client=_FakeClickHouseClient())
    session = SimpleNamespace()

    sales = await warehouse.get_sales(session, days=7)
    assert sales["source"] == "clickhouse"
    assert sales["window_days"] == 7
    assert sales["orders"] == 3
    assert sales["total_sales"] == Decimal("1200.00")
    assert sales["avg_order_amount"] == Decimal("400.00")
    assert sales["status_breakdown"] == {"completed": 2, "pending": 1}
