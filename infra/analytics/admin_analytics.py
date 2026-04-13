from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.analytics.clickhouse_client import ClickHouseClient
from infra.db.models.orders import OrderModel
from infra.db.models.production import ProductionLineModel, WorkOrderModel

SYNC_INTERVAL_SECONDS = 30


def _to_clickhouse_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _to_clickhouse_date(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _decimal_to_str(value: Decimal | None) -> str:
    return str(value or Decimal("0"))


def _sql_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class AdminAnalyticsWarehouse:
    def __init__(self, client: ClickHouseClient | None = None) -> None:
        self.client = client or ClickHouseClient()
        self._last_synced_at: dict[str, datetime] = {}
        self._sync_locks: dict[str, asyncio.Lock] = {}

    async def get_overview(self, session: AsyncSession) -> dict[str, Any]:
        if not await self._sync_orders(session):
            return await self._get_overview_from_postgres(session)

        now = datetime.now(timezone.utc)
        start_today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        end_today = start_today + timedelta(days=1)
        overview_rows = await self.client.query_json_rows(
            """
            SELECT
                countIf(created_at >= toDateTime('{start_today}') AND created_at < toDateTime('{end_today}')) AS orders_today,
                count() AS total_orders,
                countIf(status = 'pending') AS pending_orders,
                countIf(status IN ('producing', 'in_production')) AS producing_orders,
                countIf(status = 'completed') AS completed_orders
            FROM order_snapshots
            """.format(
                start_today=_to_clickhouse_datetime(start_today),
                end_today=_to_clickhouse_datetime(end_today),
            )
        )
        work_order_rows = await self.client.query_json_rows(
            """
            SELECT countIf(status IN ('pending', 'in_progress')) AS active_work_orders
            FROM work_order_snapshots
            """
        )

        overview = overview_rows[0] if overview_rows else {}
        active_work_orders = work_order_rows[0] if work_order_rows else {}
        return {
            "kpis": {
                "orders_today": int(overview.get("orders_today", 0) or 0),
                "total_orders": int(overview.get("total_orders", 0) or 0),
                "pending_orders": int(overview.get("pending_orders", 0) or 0),
                "producing_orders": int(overview.get("producing_orders", 0) or 0),
                "completed_orders": int(overview.get("completed_orders", 0) or 0),
                "active_work_orders": int(active_work_orders.get("active_work_orders", 0) or 0),
            },
            "generated_at": now,
            "source": "clickhouse",
        }

    async def get_production(self, session: AsyncSession) -> dict[str, Any]:
        if not await self._sync_work_orders(session):
            return await self._get_production_from_postgres(session)

        status_rows = await self.client.query_json_rows(
            """
            SELECT status, count() AS work_order_count
            FROM work_order_snapshots
            GROUP BY status
            ORDER BY status ASC
            """
        )
        line_rows = await self.client.query_json_rows(
            """
            SELECT id, line_code, line_name, work_order_count
            FROM production_line_snapshots
            ORDER BY line_code ASC
            """
        )

        return {
            "status_breakdown": {
                str(row["status"]): int(row.get("work_order_count", 0) or 0) for row in status_rows
            },
            "lines": [
                {
                    "line_id": row["id"],
                    "line_code": row["line_code"],
                    "line_name": row["line_name"],
                    "work_order_count": int(row.get("work_order_count", 0) or 0),
                }
                for row in line_rows
            ],
            "generated_at": datetime.now(timezone.utc),
            "source": "clickhouse",
        }

    async def get_sales(self, session: AsyncSession, *, days: int) -> dict[str, Any]:
        if not await self._sync_orders(session):
            return await self._get_sales_from_postgres(session, days=days)

        now = datetime.now(timezone.utc)
        start_at = now - timedelta(days=days)
        overview_rows = await self.client.query_json_rows(
            """
            SELECT
                countIf(created_at >= toDateTime('{start_at}')) AS orders,
                sumIf(total_amount, created_at >= toDateTime('{start_at}')) AS total_sales
            FROM order_snapshots
            """.format(start_at=_to_clickhouse_datetime(start_at))
        )
        status_rows = await self.client.query_json_rows(
            """
            SELECT status, count() AS order_count
            FROM order_snapshots
            WHERE created_at >= toDateTime('{start_at}')
            GROUP BY status
            ORDER BY status ASC
            """.format(start_at=_to_clickhouse_datetime(start_at))
        )

        overview = overview_rows[0] if overview_rows else {}
        total_orders = int(overview.get("orders", 0) or 0)
        total_sales = Decimal(str(overview.get("total_sales", "0") or "0"))
        avg_order_amount = Decimal("0")
        if total_orders > 0:
            avg_order_amount = total_sales / total_orders

        return {
            "window_days": days,
            "orders": total_orders,
            "total_sales": total_sales,
            "avg_order_amount": avg_order_amount,
            "status_breakdown": {
                str(row["status"]): int(row.get("order_count", 0) or 0) for row in status_rows
            },
            "generated_at": now,
            "source": "clickhouse",
        }

    async def _sync_orders(self, session: AsyncSession) -> bool:
        try:
            await self._ensure_tables()
            await self._sync_dataset("orders", self._reload_order_snapshots, session)
            await self._sync_dataset("work_orders", self._reload_work_order_snapshots, session)
            return True
        except Exception:
            return False

    async def _sync_work_orders(self, session: AsyncSession) -> bool:
        try:
            await self._ensure_tables()
            await self._sync_dataset("work_orders", self._reload_work_order_snapshots, session)
            await self._sync_dataset("production_lines", self._reload_production_line_snapshots, session)
            return True
        except Exception:
            return False

    async def _sync_dataset(self, dataset: str, loader, session: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        last_synced_at = self._last_synced_at.get(dataset)
        if last_synced_at and (now - last_synced_at).total_seconds() < SYNC_INTERVAL_SECONDS:
            return

        lock = self._sync_locks.setdefault(dataset, asyncio.Lock())
        async with lock:
            last_synced_at = self._last_synced_at.get(dataset)
            if last_synced_at and (now - last_synced_at).total_seconds() < SYNC_INTERVAL_SECONDS:
                return
            await loader(session)
            self._last_synced_at[dataset] = datetime.now(timezone.utc)

    async def _ensure_tables(self) -> None:
        await self.client.execute(
            """
            CREATE TABLE IF NOT EXISTS order_snapshots (
                id String,
                order_no String,
                customer_id String,
                status String,
                priority String,
                total_amount Decimal(15, 2),
                total_quantity Int32,
                total_area_sqm Decimal(12, 4),
                expected_delivery_date DateTime,
                confirmed_at Nullable(DateTime),
                pickup_approved_at Nullable(DateTime),
                picked_up_at Nullable(DateTime),
                cancelled_at Nullable(DateTime),
                created_at DateTime,
                updated_at DateTime
            ) ENGINE = MergeTree
            ORDER BY (created_at, id)
            """
        )
        await self.client.execute(
            """
            CREATE TABLE IF NOT EXISTS work_order_snapshots (
                id String,
                work_order_no String,
                order_id String,
                production_line_id Nullable(String),
                process_step_key String,
                status String,
                glass_type String,
                specification String,
                quantity Int32,
                completed_qty Int32,
                defect_qty Int32,
                scheduled_date Nullable(Date),
                started_at Nullable(DateTime),
                completed_at Nullable(DateTime),
                created_at DateTime,
                updated_at DateTime
            ) ENGINE = MergeTree
            ORDER BY (created_at, id)
            """
        )
        await self.client.execute(
            """
            CREATE TABLE IF NOT EXISTS production_line_snapshots (
                id String,
                line_code String,
                line_name String,
                is_active UInt8,
                work_order_count Int32,
                created_at DateTime
            ) ENGINE = MergeTree
            ORDER BY (line_code, id)
            """
        )

    async def _reload_order_snapshots(self, session: AsyncSession) -> None:
        result = await session.execute(select(OrderModel).order_by(OrderModel.created_at.asc()))
        rows = list(result.scalars().all())
        await self.client.execute("TRUNCATE TABLE order_snapshots")
        await self.client.insert_json_rows(
            "order_snapshots",
            [
                {
                    "id": row.id,
                    "order_no": row.order_no,
                    "customer_id": row.customer_id,
                    "status": row.status,
                    "priority": row.priority,
                    "total_amount": _decimal_to_str(row.total_amount),
                    "total_quantity": int(row.total_quantity or 0),
                    "total_area_sqm": _decimal_to_str(row.total_area_sqm),
                    "expected_delivery_date": _to_clickhouse_datetime(row.expected_delivery_date),
                    "confirmed_at": _to_clickhouse_datetime(row.confirmed_at),
                    "pickup_approved_at": _to_clickhouse_datetime(row.pickup_approved_at),
                    "picked_up_at": _to_clickhouse_datetime(row.picked_up_at),
                    "cancelled_at": _to_clickhouse_datetime(row.cancelled_at),
                    "created_at": _to_clickhouse_datetime(row.created_at),
                    "updated_at": _to_clickhouse_datetime(row.updated_at),
                }
                for row in rows
            ],
        )

    async def _reload_work_order_snapshots(self, session: AsyncSession) -> None:
        result = await session.execute(select(WorkOrderModel).order_by(WorkOrderModel.created_at.asc()))
        rows = list(result.scalars().all())
        await self.client.execute("TRUNCATE TABLE work_order_snapshots")
        await self.client.insert_json_rows(
            "work_order_snapshots",
            [
                {
                    "id": row.id,
                    "work_order_no": row.work_order_no,
                    "order_id": row.order_id,
                    "production_line_id": row.production_line_id,
                    "process_step_key": row.process_step_key,
                    "status": row.status,
                    "glass_type": row.glass_type,
                    "specification": row.specification,
                    "quantity": int(row.quantity or 0),
                    "completed_qty": int(row.completed_qty or 0),
                    "defect_qty": int(row.defect_qty or 0),
                    "scheduled_date": _to_clickhouse_date(row.scheduled_date),
                    "started_at": _to_clickhouse_datetime(row.started_at),
                    "completed_at": _to_clickhouse_datetime(row.completed_at),
                    "created_at": _to_clickhouse_datetime(row.created_at),
                    "updated_at": _to_clickhouse_datetime(row.updated_at),
                }
                for row in rows
            ],
        )

    async def _reload_production_line_snapshots(self, session: AsyncSession) -> None:
        count_rows = await session.execute(
            select(
                ProductionLineModel.id,
                ProductionLineModel.line_code,
                ProductionLineModel.line_name,
                ProductionLineModel.is_active,
                ProductionLineModel.created_at,
                func.count(WorkOrderModel.id),
            )
            .select_from(ProductionLineModel)
            .join(
                WorkOrderModel,
                WorkOrderModel.production_line_id == ProductionLineModel.id,
                isouter=True,
            )
            .group_by(
                ProductionLineModel.id,
                ProductionLineModel.line_code,
                ProductionLineModel.line_name,
                ProductionLineModel.is_active,
                ProductionLineModel.created_at,
            )
            .order_by(ProductionLineModel.line_code.asc())
        )
        rows = list(count_rows.all())
        await self.client.execute("TRUNCATE TABLE production_line_snapshots")
        await self.client.insert_json_rows(
            "production_line_snapshots",
            [
                {
                    "id": line_id,
                    "line_code": line_code,
                    "line_name": line_name,
                    "is_active": 1 if is_active else 0,
                    "work_order_count": int(work_order_count or 0),
                    "created_at": _to_clickhouse_datetime(created_at),
                }
                for line_id, line_code, line_name, is_active, created_at, work_order_count in rows
            ],
        )

    async def _get_overview_from_postgres(self, session: AsyncSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start_today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        end_today = start_today + timedelta(days=1)

        orders_today = await session.scalar(
            select(func.count(OrderModel.id)).where(
                OrderModel.created_at >= start_today,
                OrderModel.created_at < end_today,
            )
        )
        total_orders = await session.scalar(select(func.count(OrderModel.id)))
        pending_orders = await session.scalar(
            select(func.count(OrderModel.id)).where(OrderModel.status == "pending")
        )
        producing_orders = await session.scalar(
            select(func.count(OrderModel.id)).where(
                OrderModel.status.in_(["producing", "in_production"])
            )
        )
        completed_orders = await session.scalar(
            select(func.count(OrderModel.id)).where(OrderModel.status == "completed")
        )
        active_work_orders = await session.scalar(
            select(func.count(WorkOrderModel.id)).where(
                WorkOrderModel.status.in_(["pending", "in_progress"])
            )
        )

        return {
            "kpis": {
                "orders_today": int(orders_today or 0),
                "total_orders": int(total_orders or 0),
                "pending_orders": int(pending_orders or 0),
                "producing_orders": int(producing_orders or 0),
                "completed_orders": int(completed_orders or 0),
                "active_work_orders": int(active_work_orders or 0),
            },
            "generated_at": now,
            "source": "postgres_fallback",
        }

    async def _get_production_from_postgres(self, session: AsyncSession) -> dict[str, Any]:
        status_rows = await session.execute(
            select(WorkOrderModel.status, func.count(WorkOrderModel.id))
            .group_by(WorkOrderModel.status)
            .order_by(WorkOrderModel.status.asc())
        )
        line_rows = await session.execute(
            select(
                ProductionLineModel.id,
                ProductionLineModel.line_code,
                ProductionLineModel.line_name,
                func.count(WorkOrderModel.id),
            )
            .select_from(ProductionLineModel)
            .join(
                WorkOrderModel,
                WorkOrderModel.production_line_id == ProductionLineModel.id,
                isouter=True,
            )
            .group_by(
                ProductionLineModel.id,
                ProductionLineModel.line_code,
                ProductionLineModel.line_name,
            )
            .order_by(ProductionLineModel.line_code.asc())
        )

        return {
            "status_breakdown": {
                status: int(count) for status, count in status_rows.all()
            },
            "lines": [
                {
                    "line_id": line_id,
                    "line_code": line_code,
                    "line_name": line_name,
                    "work_order_count": int(work_order_count),
                }
                for line_id, line_code, line_name, work_order_count in line_rows.all()
            ],
            "generated_at": datetime.now(timezone.utc),
            "source": "postgres_fallback",
        }

    async def _get_sales_from_postgres(self, session: AsyncSession, *, days: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start_at = now - timedelta(days=days)

        order_count = await session.scalar(
            select(func.count(OrderModel.id)).where(OrderModel.created_at >= start_at)
        )
        total_sales = await session.scalar(
            select(func.coalesce(func.sum(OrderModel.total_amount), Decimal("0"))).where(
                OrderModel.created_at >= start_at
            )
        )
        status_rows = await session.execute(
            select(OrderModel.status, func.count(OrderModel.id))
            .where(OrderModel.created_at >= start_at)
            .group_by(OrderModel.status)
            .order_by(OrderModel.status.asc())
        )

        total_orders_int = int(order_count or 0)
        total_sales_decimal = total_sales or Decimal("0")
        avg_order_amount = Decimal("0")
        if total_orders_int > 0:
            avg_order_amount = total_sales_decimal / total_orders_int

        return {
            "window_days": days,
            "orders": total_orders_int,
            "total_sales": total_sales_decimal,
            "avg_order_amount": avg_order_amount,
            "status_breakdown": {status: int(count) for status, count in status_rows.all()},
            "generated_at": now,
            "source": "postgres_fallback",
        }
