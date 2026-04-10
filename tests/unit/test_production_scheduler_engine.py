from datetime import date
from decimal import Decimal

from domains.production.scheduler_engine import (
    ProductionLine,
    ProductionSchedulerEngine,
    WorkOrderCandidate,
)


def test_scheduler_keeps_backward_compatible_id_mode() -> None:
    engine = ProductionSchedulerEngine()
    result = engine.schedule(["wo-1", "wo-2"], _day=date(2026, 4, 9))

    assert result.scheduled_work_order_ids == ["wo-1", "wo-2"]
    assert result.unscheduled_work_order_ids == []


def test_scheduler_applies_constraints_and_capacity() -> None:
    engine = ProductionSchedulerEngine(
        [
            ProductionLine(
                line_id="line-a",
                line_name="Line A",
                supported_glass_types={"tempered"},
                max_width_mm=3000,
                max_height_mm=3000,
                daily_capacity_sqm=Decimal("5.0"),
                supported_processes={"temper"},
            )
        ]
    )

    candidates = [
        WorkOrderCandidate(
            work_order_id="wo-1",
            order_no="GF-001",
            glass_type="tempered",
            specification="6mm",
            width_mm=1000,
            height_mm=1200,
            quantity=1,
            area_sqm=Decimal("2.0"),
            process_requirements="temper",
            expected_delivery_date=date(2026, 4, 11),
        ),
        WorkOrderCandidate(
            work_order_id="wo-2",
            order_no="GF-002",
            glass_type="tempered",
            specification="8mm",
            width_mm=1200,
            height_mm=1200,
            quantity=1,
            area_sqm=Decimal("3.5"),
            process_requirements="temper",
            expected_delivery_date=date(2026, 4, 12),
        ),
        WorkOrderCandidate(
            work_order_id="wo-3",
            order_no="GF-003",
            glass_type="tempered",
            specification="6mm",
            width_mm=1000,
            height_mm=1000,
            quantity=1,
            area_sqm=Decimal("1.0"),
            process_requirements="laminate",
            expected_delivery_date=date(2026, 4, 12),
        ),
        WorkOrderCandidate(
            work_order_id="wo-4",
            order_no="GF-004",
            glass_type="tempered",
            specification="12mm",
            width_mm=4000,
            height_mm=1000,
            quantity=1,
            area_sqm=Decimal("1.0"),
            process_requirements="temper",
            expected_delivery_date=date(2026, 4, 12),
        ),
    ]

    result = engine.schedule(
        candidates=candidates,
        start_date=date(2026, 4, 9),
        horizon_days=3,
    )

    assert result.scheduled_work_order_ids == ["wo-1", "wo-2"]
    assert set(result.unscheduled_work_order_ids) == {"wo-3", "wo-4"}

    scheduled_by_id = {slot.work_order_id: slot for slot in result.scheduled}
    assert scheduled_by_id["wo-1"].scheduled_date == date(2026, 4, 9)
    assert scheduled_by_id["wo-2"].scheduled_date == date(2026, 4, 10)
