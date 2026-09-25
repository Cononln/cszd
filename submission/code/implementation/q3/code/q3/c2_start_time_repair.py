"""Deterministic C2-A transport start-time repair.

This module deliberately stays on the Q3 side of the frozen Q2 contract.  It
reuses Q2's route evaluator, fleet and battery data and emits a complete
``ScheduleResult``; it never edits Q2 result CSVs or changes a Q2 formula.
Every emitted schedule is subsequently replayed by ``validate_solution``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

# Importing the formal transport adapter first registers the sibling Q2 code
# root.  C2 therefore shares the exact Q2 package rather than vendoring it.
from . import transport_adapter as _transport_adapter  # noqa: F401
from q2 import schedule_decoder as q2_decoder
from q2.models import Q2State, ScheduleAssignment, ScheduleResult
from common.physics import charge_time


# The repair neighborhood is a deterministic wave plan, not a formal result.
# Its values are only start-time proposals; the resource-ready time and the
# original Q2 hard validator remain authoritative.  Keeping this small and
# explicit makes the C2-A experiment reproducible and auditable.
WAVE_STARTS_S: dict[str, float] = {
    "T001": 0.0, "T002": 8000.0, "T003": 13000.0, "T004": 1400.0,
    "T005": 16000.0, "T006": 5000.0, "T007": 10430.0, "T008": 3800.0,
    "T009": 19000.0, "T010": 6000.0, "T011": 22000.0, "T012": 0.0,
    "T013": 9000.0, "T014": 1600.0, "T015": 4300.0, "T016": 8000.0,
    "T017": 16000.0, "T018": 600.0, "T019": 5000.0, "T020": 14000.0,
    "T021": 2327.0, "T022": 600.0, "T023": 2150.0, "T024": 5940.0,
    "T025": 18000.0,
}


@dataclass(frozen=True)
class RepairAudit:
    operator: str
    target_start_s: Mapping[str, float]
    changed_trips: tuple[str, ...]
    waiting_time_before_s: float
    waiting_time_after_s: float
    makespan_before_s: float
    makespan_after_s: float
    energy_before_kwh: float
    energy_after_kwh: float
    resource_event_count_before: int
    resource_event_count_after: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "target_start_s": dict(self.target_start_s),
            "changed_trips": list(self.changed_trips),
            "waiting_time_before_s": self.waiting_time_before_s,
            "waiting_time_after_s": self.waiting_time_after_s,
            "makespan_before_s": self.makespan_before_s,
            "makespan_after_s": self.makespan_after_s,
            "energy_before_kwh": self.energy_before_kwh,
            "energy_after_kwh": self.energy_after_kwh,
            "resource_event_count_before": self.resource_event_count_before,
            "resource_event_count_after": self.resource_event_count_after,
        }


def _schedule_dict(schedule: ScheduleResult) -> dict[str, Any]:
    return {
        "status": schedule.status,
        "solver_status": schedule.solver_status,
        "stage_statuses": dict(schedule.stage_statuses),
        "metrics": dict(schedule.metrics),
        "checks": dict(schedule.checks),
        "assignments": [a.__dict__ for a in schedule.assignments],
        "trip_records": [dict(r) for r in schedule.trip_records],
    }


def repair_start_times(state: Q2State, baseline: ScheduleResult,
                       *, target_starts: Mapping[str, float] | None = None) -> tuple[ScheduleResult, RepairAudit]:
    """Apply the deterministic wave neighborhood under real resource release.

    Each proposed start is delayed, when necessary, until a same-type UAV and
    battery are both released.  The Q2 validator—not this function—decides
    whether deadlines and all other hard constraints remain satisfied.
    """
    target = dict(target_starts or WAVE_STARTS_S)
    boxes = q2_decoder._box_rows()
    evals = q2_decoder._evaluations(state)
    uavs, batteries = q2_decoder._resource_ids()
    types = q2_decoder.load_transport_types()
    battery_cfg = q2_decoder.load_transport_batteries()
    order = sorted(range(len(state.trips)), key=lambda i: (float(target.get(f"T{i + 1:03d}", 0.0)), i))
    uav_ready = {uid: 0.0 for values in uavs.values() for uid in values}
    battery_ready = {bid: 0.0 for values in batteries.values() for bid in values}
    assignments: list[ScheduleAssignment | None] = [None] * len(state.trips)
    records: list[dict[str, Any] | None] = [None] * len(state.trips)
    for index in order:
        trip = state.trips[index]
        evaluation = evals[index]
        gtype = trip.gtype
        energy = float(evaluation.total_route_energy_kwh)
        soc = 1.0 - energy / float(types[gtype]["Euse"])
        charge = float(charge_time(battery_cfg[gtype]["t_full"], max(0.0, soc)))
        proposed = float(target.get(f"T{index + 1:03d}", 0.0))
        start, uid, battery_id = min(
            (max(uav_ready[uid], battery_ready[battery_id]), uid, battery_id)
            for uid in uavs[gtype] for battery_id in batteries[gtype])
        start = max(proposed, start)
        return_time = start + float(evaluation.route_duration_s)
        uav_ready[uid] = return_time
        battery_ready[battery_id] = return_time + charge
        assignments[index] = ScheduleAssignment(f"T{index + 1:03d}", uid, battery_id, start)
        records[index] = q2_decoder._make_record(index, trip, evaluation, uid, battery_id,
                                                  start, boxes, charge)
    repaired = q2_decoder._assemble_result(
        "FEASIBLE", "C2_START_TIME_REPAIR", assignments, records,
        runtime_s=0.0,
        stage_statuses={"WTD": "C2_START_TIME_REPAIR", "Cmax": "C2_START_TIME_REPAIR"},
    )
    before_starts = {a.trip_id: float(a.start_time_s) for a in baseline.assignments}
    after_starts = {a.trip_id: float(a.start_time_s) for a in repaired.assignments}
    changed = tuple(tid for tid in sorted(after_starts)
                    if abs(after_starts[tid] - before_starts.get(tid, 0.0)) > 1e-7)
    audit = RepairAudit(
        operator="spread_blind_intervals_with_resource_ready",
        target_start_s=target,
        changed_trips=changed,
        waiting_time_before_s=sum(max(0.0, float(a.start_time_s)) for a in baseline.assignments),
        waiting_time_after_s=sum(max(0.0, float(a.start_time_s)) for a in repaired.assignments),
        makespan_before_s=float(baseline.metrics.get("Cmax_s", 0.0)),
        makespan_after_s=float(repaired.metrics.get("Cmax_s", 0.0)),
        energy_before_kwh=float(baseline.metrics.get("total_energy_kwh", 0.0)),
        energy_after_kwh=float(repaired.metrics.get("total_energy_kwh", 0.0)),
        resource_event_count_before=2 * len(baseline.trip_records),
        resource_event_count_after=2 * len(repaired.trip_records),
    )
    return repaired, audit


def schedule_to_dict(schedule: ScheduleResult) -> dict[str, Any]:
    return _schedule_dict(schedule)
