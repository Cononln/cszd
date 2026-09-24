"""Q2-C resource decoder.

The outer Q2-D search only changes transport structure.  This module turns a
fixed collection of Q2-B routes into an executable timeline using the real
fleet and the real shared batteries.  CP-SAT owns the discrete resource
assignment and start times; the returned event records are subsequently
replayed by :mod:`validate_q2`.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any

Q2_DIR = Path(__file__).resolve().parents[2]
Q1_CODE = Q2_DIR.parent / "q1" / "code"
sys.path.insert(0, str(Q1_CODE))

from common.data import (  # noqa: E402
    load_boxes,
    load_transport_batteries,
    load_transport_fleet,
    load_transport_types,
)
from common.physics import charge_time  # noqa: E402

try:
    from ortools.sat.python import cp_model  # type: ignore
except Exception:  # pragma: no cover - minimal environments only
    cp_model = None

from .deadlines import hard_deadline  # noqa: E402
from .models import Q2State, ScheduleAssignment, ScheduleResult  # noqa: E402
from .route_evaluator import evaluate_route_cached  # noqa: E402

TIME_SCALE = 10  # 0.1 s integer CP-SAT grid; deadlines remain conservative.
PRIORITY_SCALE = 1000  # exact integer representation of the input priority column.
TOL = 1e-7


def _route_key(trip) -> tuple:
    return (trip.gtype, tuple(trip.stop_sequence),
            tuple((sid, tuple(trip.boxes_by_stop[sid])) for sid in trip.stop_sequence))


def _evaluations(state: Q2State):
    return [evaluate_route_cached(*_route_key(trip)) for trip in state.trips]


def _box_rows() -> dict[str, dict[str, Any]]:
    return {str(r["box"]): r for r in load_boxes().to_dict("records")}


def _resource_ids() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    fleet = load_transport_fleet()
    uavs = {g: [str(x.uid) for x in fleet.itertuples() if str(x.gtype) == g]
            for g in ("A", "B", "C")}
    batteries = load_transport_batteries()
    bats = {g: [f"BAT-{g}-{i:02d}" for i in range(1, int(v["n"]) + 1)]
            for g, v in batteries.items()}
    return uavs, bats


def _precheck(evals, boxes: dict[str, dict[str, Any]]) -> tuple[bool, dict[str, bool]]:
    checks = {"route_feasibility": all(bool(ev.route_feasible) for ev in evals),
              "hard_deadline_lower_bound": True}
    for ev in evals:
        for sid, offset in ev.delivery_offset_by_sid.items():
            for box in ev.route.boxes_by_stop[sid]:
                dl = hard_deadline(boxes[box])
                if dl is not None and float(offset) > float(dl) + TOL:
                    checks["hard_deadline_lower_bound"] = False
    return all(checks.values()), checks


def _make_record(idx, trip, ev, uid, bid, start, boxes, charge) -> dict[str, Any]:
    gt = load_transport_types()[trip.gtype]
    e = float(ev.total_route_energy_kwh)
    ret = float(start + float(ev.route_duration_s))
    delivery_by_box = {}
    lateness = 0.0
    for sid in trip.stop_sequence:
        delivery = float(start + ev.delivery_offset_by_sid[sid])
        for box in trip.boxes_by_stop[sid]:
            delivery_by_box[box] = delivery
            row = boxes[box]
            lateness += float(row["prio"]) * max(0.0, delivery - float(row["t_exp"]))
    return {
        "trip_id": f"T{idx+1:03d}", "gtype": trip.gtype,
        "stop_sequence": list(trip.stop_sequence),
        "boxes_by_stop": {s: list(trip.boxes_by_stop[s]) for s in trip.stop_sequence},
        "uid": uid, "battery_id": bid,
        "start_time_s": float(start),
        "departure_time_s": float(start + float(ev.prep_load_time_s)),
        "return_time_s": ret,
        "charge_start_s": ret, "charge_end_s": float(ret + charge),
        "charge_time_s": float(charge),
        "route_duration_s": float(ev.route_duration_s),
        "total_energy_kwh": e,
        "soc_after": float(1.0 - e / float(gt["Euse"])),
        "delivery_by_box_s": delivery_by_box,
        "delivery_offset_by_sid_s": {s: float(ev.delivery_offset_by_sid[s])
                                      for s in trip.stop_sequence},
        "wtd_contribution": float(lateness),
        "legs": [{"from": l.from_node, "to": l.to_node,
                  "payload_kg": float(l.payload_kg), "time_s": float(l.time_s),
                  "energy_kwh": float(l.energy_kwh)} for l in ev.legs],
    }


def _timeline_checks(records: tuple[dict[str, Any], ...]) -> dict[str, bool]:
    def overlap(vals):
        vals = sorted(vals)
        return all(b[0] >= a[1] - TOL for a, b in zip(vals, vals[1:]))
    by_uav, by_bat = {}, {}
    fleet = load_transport_fleet()
    fleet_types = {str(r.uid): str(r.gtype) for r in fleet.itertuples()}
    for r in records:
        by_uav.setdefault(r["uid"], []).append((r["start_time_s"], r["return_time_s"]))
        by_bat.setdefault(r["battery_id"], []).append((r["start_time_s"], r["charge_end_s"]))
    reuse_rows = battery_reuse_rows(records)
    return {
        "uav_type": all(fleet_types.get(r["uid"]) == r["gtype"] for r in records),
        "uav_overlap": all(overlap(v) for v in by_uav.values()),
        "battery_overlap": all(overlap(v) for v in by_bat.values()),
        "battery_type": all(r["battery_id"][4] == r["gtype"] for r in records),
        "soc": all(-TOL <= float(r["soc_after"]) <= 1.0 + TOL for r in records),
        "charge_before_reuse": all(float(x["margin_s"]) >= -TOL for x in reuse_rows),
    }


def battery_reuse_rows(records: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return explicit consecutive-use margins for each shared battery."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["battery_id"]), []).append(record)
    rows: list[dict[str, Any]] = []
    for battery_id, seq in grouped.items():
        seq.sort(key=lambda r: float(r["start_time_s"]))
        for previous, current in zip(seq, seq[1:]):
            margin = float(current["start_time_s"]) - float(previous["charge_end_s"])
            rows.append({"battery_id": battery_id,
                         "previous_trip": previous["trip_id"],
                         "previous_charge_end": previous["charge_end_s"],
                         "next_trip": current["trip_id"],
                         "next_start": current["start_time_s"],
                         "margin_s": margin,
                         "pass": margin >= -TOL})
    return rows


def _assemble_result(status, solver_status, assignments, records, *,
                     runtime_s=0.0, stage_statuses=None, solver_metrics=None) -> ScheduleResult:
    records = tuple(records)
    checks = _timeline_checks(records)
    metrics = {
        "WTD": float(sum(float(r["wtd_contribution"]) for r in records)),
        "Cmax_s": float(max((r["return_time_s"] for r in records), default=0.0)),
        "total_energy_kwh": float(sum(float(r["total_energy_kwh"]) for r in records)),
        "n_trips": float(len(records)),
        "total_operation_time_s": float(sum(float(r["route_duration_s"]) for r in records)),
    }
    return ScheduleResult(status=status, assignments=tuple(assignments),
                          trip_records=records, metrics=metrics, checks=checks,
                          solver_status=solver_status,
                          stage_statuses=stage_statuses or {"WTD": solver_status, "Cmax": solver_status},
                          solver_metrics=solver_metrics or {}, runtime_s=float(runtime_s))


def _fallback_schedule(state: Q2State, evals, boxes, runtime_s=0.0) -> ScheduleResult:
    """Portable list scheduler used only when OR-Tools is unavailable."""
    uavs, bats = _resource_ids()
    uav_ready = {u: 0.0 for ids in uavs.values() for u in ids}
    bat_ready = {b: 0.0 for ids in bats.values() for b in ids}
    assignments, records = [], []
    for idx, (trip, ev) in enumerate(zip(state.trips, evals)):
        g = trip.gtype
        options = [(max(uav_ready[u], bat_ready[b]), u, b)
                   for u in uavs[g] for b in bats[g]]
        if not options:
            return ScheduleResult("INFEASIBLE", solver_status="NO_RESOURCE",
                                  runtime_s=runtime_s)
        start, uid, bid = min(options)
        for sid, offset in ev.delivery_offset_by_sid.items():
            for box in trip.boxes_by_stop[sid]:
                dl = hard_deadline(boxes[box])
                if dl is not None and start + offset > dl + TOL:
                    return ScheduleResult("INFEASIBLE", solver_status="FALLBACK_DEADLINE",
                                          runtime_s=runtime_s)
        e = float(ev.total_route_energy_kwh)
        gt = load_transport_types()[g]
        soc = 1.0 - e / float(gt["Euse"])
        ch = float(charge_time(load_transport_batteries()[g]["t_full"], max(0.0, soc)))
        ret = start + float(ev.route_duration_s)
        uav_ready[uid], bat_ready[bid] = ret, ret + ch
        assignments.append(ScheduleAssignment(f"T{idx+1:03d}", uid, bid, start))
        records.append(_make_record(idx, trip, ev, uid, bid, start, boxes, ch))
    return _assemble_result("FEASIBLE", "FALLBACK", assignments, records,
                            runtime_s=runtime_s)


def decode_schedule(state: Q2State, *, cp_workers: int = 1,
                    time_limit_s: float = 60.0, fixed_seed: int = 0) -> ScheduleResult:
    """Decode fixed routes into UAV/battery/timeline resources."""
    started = time.perf_counter()
    boxes = _box_rows()
    evals = _evaluations(state)
    ok, prechecks = _precheck(evals, boxes)
    if not ok:
        return ScheduleResult("INFEASIBLE", checks=prechecks,
                              solver_status="PRECHECK_FAIL",
                              runtime_s=time.perf_counter() - started)
    if cp_model is None:
        return _fallback_schedule(state, evals, boxes,
                                  runtime_s=time.perf_counter() - started)

    uavs, bats = _resource_ids()
    fleet_bat = load_transport_batteries()
    gt_params = load_transport_types()
    n = len(state.trips)
    durations = [max(1, int(math.ceil(float(ev.route_duration_s) * TIME_SCALE)))
                 for ev in evals]
    charge_durations = []
    for trip, ev in zip(state.trips, evals):
        g = trip.gtype
        e = float(ev.total_route_energy_kwh)
        soc = 1.0 - e / float(gt_params[g]["Euse"])
        ch = charge_time(float(fleet_bat[g]["t_full"]), max(0.0, soc))
        charge_durations.append(max(0, int(math.ceil(ch * TIME_SCALE))))
    hard_values = []
    for row in load_boxes().to_dict("records"):
        dl = hard_deadline(row)
        if dl is not None:
            hard_values.append(float(dl))
    horizon_s = max(24 * 3600.0, max(hard_values, default=0.0) + 4 * 3600.0,
                    (sum(durations) + sum(charge_durations)) / TIME_SCALE + 3600.0)
    horizon = int(math.ceil(horizon_s * TIME_SCALE))
    model = cp_model.CpModel()
    starts = [model.NewIntVar(0, horizon, f"start_{i}") for i in range(n)]
    ends = [model.NewIntVar(0, horizon + max(durations), f"end_{i}") for i in range(n)]
    for i in range(n):
        model.Add(ends[i] == starts[i] + durations[i])
    uav_lits, bat_lits = {}, {}
    for i, trip in enumerate(state.trips):
        g = trip.gtype
        u_lits = []
        for uid in uavs[g]:
            lit = model.NewBoolVar(f"uav_{i}_{uid}")
            uav_lits[(i, uid)] = lit
            u_lits.append(lit)
            model.NewOptionalIntervalVar(starts[i], durations[i], ends[i], lit,
                                         f"uav_int_{i}_{uid}")
        if not u_lits:
            return ScheduleResult("INFEASIBLE", checks={"uav_count": False},
                                  solver_status="NO_UAV")
        model.AddExactlyOne(u_lits)
        b_lits = []
        bat_end = model.NewIntVar(0, horizon + max(durations) + max(charge_durations),
                                  f"battery_end_{i}")
        model.Add(bat_end == ends[i] + charge_durations[i])
        for bid in bats[g]:
            lit = model.NewBoolVar(f"bat_{i}_{bid}")
            bat_lits[(i, bid)] = lit
            b_lits.append(lit)
            model.NewOptionalIntervalVar(starts[i], durations[i] + charge_durations[i],
                                         bat_end, lit, f"bat_int_{i}_{bid}")
        if not b_lits:
            return ScheduleResult("INFEASIBLE", checks={"battery_count": False},
                                  solver_status="NO_BATTERY")
        model.AddExactlyOne(b_lits)
        for sid, offset in evals[i].delivery_offset_by_sid.items():
            for box in state.trips[i].boxes_by_stop[sid]:
                dl = hard_deadline(boxes[box])
                if dl is not None:
                    latest = int(math.floor(float(dl) * TIME_SCALE -
                                            float(offset) * TIME_SCALE + 1e-9))
                    model.Add(starts[i] <= latest)
    # Each optional interval is created once for each resource and grouped in
    # a NoOverlap.  The duplicated names are harmless and make the resource
    # constraints explicit in the model/diagnostic dump.
    for uid in (u for ids in uavs.values() for u in ids):
        intervals = []
        for i, trip in enumerate(state.trips):
            if uid in uavs[trip.gtype]:
                intervals.append(model.NewOptionalIntervalVar(
                    starts[i], durations[i], ends[i], uav_lits[(i, uid)],
                    f"uav_reuse_{i}_{uid}"))
        model.AddNoOverlap(intervals)
    for bid in (b for ids in bats.values() for b in ids):
        intervals = []
        for i, trip in enumerate(state.trips):
            if bid in bats[trip.gtype]:
                be = model.NewIntVar(0, horizon + max(durations) + max(charge_durations),
                                     f"battery_reuse_end_{i}_{bid}")
                model.Add(be == ends[i] + charge_durations[i])
                intervals.append(model.NewOptionalIntervalVar(
                    starts[i], durations[i] + charge_durations[i], be,
                    bat_lits[(i, bid)], f"battery_reuse_{i}_{bid}"))
        model.AddNoOverlap(intervals)
    # Hard-deadline cargo remains constrained above.  For all boxes, model the
    # soft expected-time lateness explicitly on the same 0.1 s grid.  This is
    # the first lexicographic scheduling objective, not a post-hoc statistic.
    lateness_vars = []
    for i, (trip, ev) in enumerate(zip(state.trips, evals)):
        for sid, offset in ev.delivery_offset_by_sid.items():
            offset_units = int(round(float(offset) * TIME_SCALE))
            for box in trip.boxes_by_stop[sid]:
                exp_units = int(round(float(boxes[box]["t_exp"]) * TIME_SCALE))
                late = model.NewIntVar(0, horizon, f"late_{i}_{box}")
                model.Add(late >= starts[i] + offset_units - exp_units)
                lateness_vars.append((int(round(float(boxes[box]["prio"]) * PRIORITY_SCALE)), late))
    wtd_expr = sum(weight * late for weight, late in lateness_vars)
    makespan = model.NewIntVar(0, horizon + max(durations), "makespan")
    model.AddMaxEquality(makespan, ends)
    stage_limit = max(0.1, float(time_limit_s) / 2.0)
    solver_wtd = cp_model.CpSolver()
    solver_wtd.parameters.max_time_in_seconds = stage_limit
    solver_wtd.parameters.num_search_workers = max(1, int(cp_workers))
    solver_wtd.parameters.random_seed = int(fixed_seed) & 0x7FFFFFFF
    model.Minimize(wtd_expr)
    status_wtd = solver_wtd.Solve(model)
    status_wtd_name = solver_wtd.StatusName(status_wtd)
    if status_wtd not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult("INFEASIBLE", checks={**prechecks, "cp_sat": False},
                              solver_status=f"WTD:{status_wtd_name}",
                              stage_statuses={"WTD": status_wtd_name, "Cmax": "NOT_RUN"},
                              runtime_s=time.perf_counter() - started)
    wtd_star = int(solver_wtd.Value(wtd_expr))
    # Lock the exact integer WTD optimum from stage S1 before minimizing
    # makespan.  This is a strict lexicographic objective: Cmax must never be
    # improved by accepting even one grid unit of additional WTD.
    model.Add(wtd_expr == wtd_star)
    model.Minimize(makespan)
    solver_cmax = cp_model.CpSolver()
    solver_cmax.parameters.max_time_in_seconds = stage_limit
    solver_cmax.parameters.num_search_workers = max(1, int(cp_workers))
    solver_cmax.parameters.random_seed = (int(fixed_seed) + 1) & 0x7FFFFFFF
    status_cmax = solver_cmax.Solve(model)
    status_cmax_name = solver_cmax.StatusName(status_cmax)
    solver = solver_cmax if status_cmax in (cp_model.OPTIMAL, cp_model.FEASIBLE) else solver_wtd
    status_name = f"WTD:{status_wtd_name};Cmax:{status_cmax_name}"
    assignments, records = [], []
    for i, (trip, ev) in enumerate(zip(state.trips, evals)):
        uid = next(uid for uid in uavs[trip.gtype]
                   if solver.Value(uav_lits[(i, uid)]))
        bid = next(bid for bid in bats[trip.gtype]
                   if solver.Value(bat_lits[(i, bid)]))
        start = solver.Value(starts[i]) / TIME_SCALE
        e = float(ev.total_route_energy_kwh)
        soc = 1.0 - e / float(gt_params[trip.gtype]["Euse"])
        ch = charge_time(float(fleet_bat[trip.gtype]["t_full"]), max(0.0, soc))
        assignments.append(ScheduleAssignment(f"T{i+1:03d}", uid, bid, start))
        records.append(_make_record(i, trip, ev, uid, bid, start, boxes, ch))
    stage2_wtd = int(solver.Value(wtd_expr))
    solver_wtd_value = stage2_wtd / (PRIORITY_SCALE * TIME_SCALE)
    return _assemble_result(
        "FEASIBLE", status_name, assignments, records,
        runtime_s=time.perf_counter() - started,
        stage_statuses={"WTD": status_wtd_name, "Cmax": status_cmax_name},
        solver_metrics={"WTD_stage1_grid": float(wtd_star / (PRIORITY_SCALE * TIME_SCALE)),
                        "WTD_stage2_grid": float(solver_wtd_value),
                        "WTD_stage1_locked": float(stage2_wtd == wtd_star),
                        "Cmax_grid_s": float(solver.Value(makespan) / TIME_SCALE)},
    )
