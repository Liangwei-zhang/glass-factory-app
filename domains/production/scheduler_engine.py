from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal


@dataclass(slots=True)
class WorkOrderCandidate:
    work_order_id: str
    order_no: str
    glass_type: str
    specification: str
    width_mm: int
    height_mm: int
    quantity: int
    area_sqm: Decimal
    process_requirements: str
    expected_delivery_date: date
    priority: int = 0


@dataclass(slots=True)
class ProductionLine:
    line_id: str
    line_name: str
    supported_glass_types: set[str]
    max_width_mm: int
    max_height_mm: int
    daily_capacity_sqm: Decimal
    supported_processes: set[str]
    current_load_sqm: Decimal = Decimal("0")


@dataclass(slots=True)
class ScheduleSlot:
    work_order_id: str
    line_id: str
    scheduled_date: date
    estimated_start_time: datetime
    estimated_end_time: datetime
    sequence: int


@dataclass
class ScheduleResult:
    scheduled: list[ScheduleSlot] = field(default_factory=list)
    unschedulable: list[tuple[str, str]] = field(default_factory=list)

    @property
    def scheduled_work_order_ids(self) -> list[str]:
        return [slot.work_order_id for slot in self.scheduled]

    @property
    def unscheduled_work_order_ids(self) -> list[str]:
        return [work_order_id for work_order_id, _ in self.unschedulable]


class ProductionSchedulerEngine:
    def __init__(self, production_lines: list[ProductionLine] | None = None) -> None:
        self.lines = {line.line_id: line for line in (production_lines or [])}

    def schedule(
        self,
        candidates: list[WorkOrderCandidate] | list[str],
        start_date: date | None = None,
        horizon_days: int = 14,
        _day: date | None = None,
    ) -> ScheduleResult:
        if not candidates:
            return ScheduleResult()

        baseline = _day or start_date or date.today()

        if all(isinstance(item, str) for item in candidates):
            work_order_ids = [str(item) for item in candidates]
            return self._schedule_ids(work_order_ids, baseline)

        typed_candidates: list[WorkOrderCandidate] = [
            item for item in candidates if isinstance(item, WorkOrderCandidate)
        ]
        if not typed_candidates:
            return ScheduleResult()

        if not self.lines:
            return self._schedule_without_lines(typed_candidates, baseline)

        return self._schedule_with_constraints(
            candidates=typed_candidates,
            start_date=baseline,
            horizon_days=horizon_days,
        )

    def _schedule_ids(self, work_order_ids: list[str], target_day: date) -> ScheduleResult:
        result = ScheduleResult()
        line_id = next(iter(self.lines), "virtual-line")

        for sequence, work_order_id in enumerate(work_order_ids, start=1):
            start_at = datetime.combine(target_day, time(hour=8), tzinfo=timezone.utc) + timedelta(
                minutes=(sequence - 1) * 30
            )
            result.scheduled.append(
                ScheduleSlot(
                    work_order_id=work_order_id,
                    line_id=line_id,
                    scheduled_date=target_day,
                    estimated_start_time=start_at,
                    estimated_end_time=start_at + timedelta(minutes=30),
                    sequence=sequence,
                )
            )

        return result

    def _schedule_without_lines(
        self,
        candidates: list[WorkOrderCandidate],
        target_day: date,
    ) -> ScheduleResult:
        result = ScheduleResult()
        for sequence, candidate in enumerate(candidates, start=1):
            start_at = datetime.combine(target_day, time(hour=8), tzinfo=timezone.utc) + timedelta(
                minutes=(sequence - 1) * 30
            )
            result.scheduled.append(
                ScheduleSlot(
                    work_order_id=candidate.work_order_id,
                    line_id="unassigned",
                    scheduled_date=target_day,
                    estimated_start_time=start_at,
                    estimated_end_time=start_at + timedelta(minutes=30),
                    sequence=sequence,
                )
            )
        return result

    def _schedule_with_constraints(
        self,
        candidates: list[WorkOrderCandidate],
        start_date: date,
        horizon_days: int,
    ) -> ScheduleResult:
        result = ScheduleResult()

        sorted_candidates = sorted(
            candidates,
            key=lambda item: (-item.priority, item.expected_delivery_date, item.work_order_id),
        )

        line_calendar: dict[str, dict[date, Decimal]] = {line_id: {} for line_id in self.lines}
        sequence_tracker: dict[tuple[str, date], int] = {}

        for candidate in sorted_candidates:
            compatible_lines = self._find_compatible_lines(candidate)
            if not compatible_lines:
                result.unschedulable.append(
                    (candidate.work_order_id, "no compatible production line")
                )
                continue

            reserve_days = 2
            deadline = min(
                candidate.expected_delivery_date - timedelta(days=reserve_days),
                start_date + timedelta(days=max(horizon_days - 1, 0)),
            )
            if deadline < start_date:
                deadline = start_date

            assigned = False
            for offset in range(horizon_days):
                target_date = start_date + timedelta(days=offset)
                if target_date > deadline:
                    break
                if target_date.weekday() >= 6:
                    continue

                for line in compatible_lines:
                    used_capacity = line_calendar[line.line_id].get(target_date, Decimal("0"))
                    remaining_capacity = line.daily_capacity_sqm - used_capacity

                    if remaining_capacity < candidate.area_sqm:
                        continue

                    key = (line.line_id, target_date)
                    sequence = sequence_tracker.get(key, 0) + 1
                    sequence_tracker[key] = sequence

                    start_at = datetime.combine(
                        target_date, time(hour=8), tzinfo=timezone.utc
                    ) + timedelta(minutes=(sequence - 1) * 30)
                    duration_minutes = max(30, int(candidate.area_sqm * Decimal("15")))
                    result.scheduled.append(
                        ScheduleSlot(
                            work_order_id=candidate.work_order_id,
                            line_id=line.line_id,
                            scheduled_date=target_date,
                            estimated_start_time=start_at,
                            estimated_end_time=start_at + timedelta(minutes=duration_minutes),
                            sequence=sequence,
                        )
                    )

                    line_calendar[line.line_id][target_date] = used_capacity + candidate.area_sqm
                    line.current_load_sqm += candidate.area_sqm
                    assigned = True
                    break

                if assigned:
                    break

            if not assigned:
                result.unschedulable.append(
                    (
                        candidate.work_order_id,
                        f"no available capacity within {horizon_days} days",
                    )
                )

        return result

    def _find_compatible_lines(self, candidate: WorkOrderCandidate) -> list[ProductionLine]:
        required_processes = {
            part.strip() for part in candidate.process_requirements.split(",") if part.strip()
        }
        compatible: list[ProductionLine] = []

        for line in self.lines.values():
            if candidate.glass_type not in line.supported_glass_types:
                continue
            if candidate.width_mm > line.max_width_mm:
                continue
            if candidate.height_mm > line.max_height_mm:
                continue
            if required_processes and not required_processes.issubset(line.supported_processes):
                continue
            compatible.append(line)

        compatible.sort(key=lambda item: item.current_load_sqm)
        return compatible
