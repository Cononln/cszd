"""Read-only bottleneck diagnostics for the frozen-Q2 C2 baseline."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _peak(intervals: list[tuple[float, float]]) -> tuple[int, float]:
    events = [(float(start), 1) for start, _ in intervals] + [(float(end), -1) for _, end in intervals]
    active = peak = 0
    for _, delta in sorted(events, key=lambda row: (row[0], row[1])):
        active += delta
        peak = max(peak, active)
    return peak, max((end for _, end in intervals), default=0.0)


def diagnose_relay_bottleneck(result) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return per-demand, overlap, pressure and aggregate diagnostic records."""
    cover = {str(row["demand_id"]): row for row in result.coverage_audit}
    option_count = defaultdict(int)
    minimum_ready: dict[str, float | None] = {}
    for option in result.service_options:
        for demand_id in option.covered_demand_ids:
            demand_id = str(demand_id)
            option_count[demand_id] += 1
            current = minimum_ready.get(demand_id)
            value = float(option.relay_ready_s)
            minimum_ready[demand_id] = value if current is None else min(current, value)
    blind_rows = []
    intervals = []
    for demand in result.demands:
        did = str(demand.demand_id)
        source = cover.get(did, {})
        start, end = float(demand.start_s), float(demand.end_s)
        intervals.append((start, end))
        blind_rows.append({
            "demand_id": did, "trip_id": str(demand.transport_trip_id), "gtype": str(demand.gtype),
            "start_s": start, "end_s": end, "duration_s": float(demand.duration_s),
            "coverable_candidate_count": int(source.get("n_covering_candidates", 0)),
            "physics_feasible_option_count": int(option_count.get(did, 0)),
            "minimum_feasible_relay_arrival_s": minimum_ready.get(did),
            "failure_class": "B2_COMMUNICATION_COVERAGE" if int(source.get("n_covering_candidates", 0)) == 0 else
                             ("B3_RELAY_UAV_CAPACITY" if result.baseline_status == "INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET" else "NONE"),
        })
    overlap_rows = []
    for left in blind_rows:
        for right in blind_rows:
            if left["demand_id"] >= right["demand_id"]:
                continue
            start = max(float(left["start_s"]), float(right["start_s"]))
            end = min(float(left["end_s"]), float(right["end_s"]))
            if end > start + 1e-7:
                overlap_rows.append({"left_demand_id": left["demand_id"], "right_demand_id": right["demand_id"],
                                     "overlap_start_s": start, "overlap_end_s": end,
                                     "overlap_duration_s": end - start})
    demand_peak, horizon = _peak(intervals)
    pressure = [{"resource": "relay_uav", "capacity": 2, "peak_required_lower_bound": demand_peak,
                 "peak_excess_lower_bound": max(0, demand_peak - 2)},
                {"resource": "energy_component", "capacity": 6, "peak_required_lower_bound": demand_peak,
                 "peak_excess_lower_bound": max(0, demand_peak - 6)}]
    summary = {
        "baseline_status": result.baseline_status,
        "decoder_status": result.decoder_status,
        "solver_status": result.solver_status,
        "reason": result.reason,
        "blind_interval_count": len(blind_rows),
        "blind_duration_s": sum(float(row["duration_s"]) for row in blind_rows),
        "blind_peak_temporal_concurrency": demand_peak,
        "candidate_count": int(result.metrics.get("candidate_count", len(result.candidates))),
        "service_option_count": int(result.metrics.get("service_option_count", len(result.service_options))),
        "relay_uav_capacity": 2,
        "energy_component_capacity": 6,
        "horizon_s": horizon,
        "primary_bottleneck": "B3_RELAY_UAV_CAPACITY" if result.baseline_status == "INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET" else "B2_COMMUNICATION_COVERAGE",
    }
    return blind_rows, overlap_rows, pressure, summary
