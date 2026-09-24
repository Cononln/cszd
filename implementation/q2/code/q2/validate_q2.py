"""Q2-E independent event-replay validator.

No ALNS summary is trusted here: route physics, delivery timestamps, resource
intervals, SOC, charge durations and the four reported metrics are recomputed
from the frozen transport state and the emitted event records.
"""
from __future__ import annotations

import math
import sys
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

from .deadlines import hard_deadline  # noqa: E402
from .models import Q2State, ScheduleResult  # noqa: E402
from .route_evaluator import evaluate_route_cached  # noqa: E402
from .schedule_decoder import decode_schedule  # noqa: E402

TOL = 1e-5


def _key(trip):
    return (trip.gtype, tuple(trip.stop_sequence),
            tuple((sid, tuple(trip.boxes_by_stop[sid])) for sid in trip.stop_sequence))


def _overlap(intervals):
    xs = sorted(intervals)
    return all(b[0] >= a[1] - TOL for a, b in zip(xs, xs[1:]))


def validate_solution(state: Q2State, schedule: ScheduleResult | None = None,
                     *, expected_box_count: int = 80,
                     expected_box_ids: set[str] | None = None) -> dict[str, Any]:
    """Replay one schedule and return a machine-readable Gate-E report."""
    if schedule is None:
        schedule = decode_schedule(state, cp_workers=1, time_limit_s=30.0, fixed_seed=0)
    boxes = {str(r["box"]): r for r in load_boxes().to_dict("records")}
    fleet = load_transport_fleet()
    fleet_types = {str(r.uid): str(r.gtype) for r in fleet.itertuples()}
    battery_cfg = load_transport_batteries()
    gt = load_transport_types()
    records = list(schedule.trip_records)
    delivered = []
    route_pass = True
    route_energy_consistent = True
    mass_pass = volume_pass = energy_pass = reserve_pass = True
    first_pass = medical_pass = True
    recomputed_wtd = 0.0
    recomputed_energy = 0.0
    recomputed_cmax = 0.0
    delivery_recomputed = True
    unknown = duplicate = missing = split = 0
    by_box_count: dict[str, int] = {}
    by_uav: dict[str, list[tuple[float, float]]] = {}
    by_battery: dict[str, list[tuple[float, float]]] = {}
    for idx, (trip, record) in enumerate(zip(state.trips, records)):
        ev = evaluate_route_cached(*_key(trip))
        route_pass &= bool(ev.route_feasible)
        mass_pass &= bool(ev.mass_feasible)
        volume_pass &= bool(ev.volume_feasible)
        energy_pass &= bool(ev.energy_feasible)
        reserve_pass &= float(ev.energy_margin_kwh) >= -TOL
        route_energy_consistent &= abs(float(record["total_energy_kwh"]) -
                                       float(ev.total_route_energy_kwh)) <= TOL
        start = float(record["start_time_s"])
        recomputed_cmax = max(recomputed_cmax, start + float(ev.route_duration_s))
        recomputed_energy += float(ev.total_route_energy_kwh)
        uid = str(record["uid"])
        bid = str(record["battery_id"])
        by_uav.setdefault(uid, []).append((start, start + float(ev.route_duration_s)))
        by_battery.setdefault(bid, []).append((start, start + float(ev.route_duration_s) +
                                               float(record["charge_time_s"])))
        for sid in trip.stop_sequence:
            expected_delivery = start + float(ev.delivery_offset_by_sid[sid])
            got_delivery = record.get("delivery_by_box_s", {})
            for box in trip.boxes_by_stop[sid]:
                by_box_count[box] = by_box_count.get(box, 0) + 1
                delivered.append(box)
                delivery_recomputed &= abs(float(got_delivery.get(box, math.nan)) -
                                          expected_delivery) <= TOL
                row = boxes.get(box)
                if row is None:
                    unknown += 1
                    continue
                d = expected_delivery
                dl = hard_deadline(row)
                if dl is not None:
                    if d > float(dl) + TOL:
                        if bool(row["first"]):
                            first_pass = False
                        if str(row["type"]).strip() == "医疗物资":
                            medical_pass = False
                recomputed_wtd += float(row["prio"]) * max(0.0, d - float(row["t_exp"]))
    expected_ids = set(expected_box_ids) if expected_box_ids is not None else set(boxes)
    duplicate = sum(v > 1 for b, v in by_box_count.items() if b in expected_ids)
    missing = len(expected_ids - set(by_box_count))
    split = duplicate
    uav_type = all(fleet_types.get(r["uid"]) == r["gtype"] for r in records)
    uav_overlap = all(_overlap(v) for v in by_uav.values())
    battery_type = all(str(r["battery_id"]).startswith(f"BAT-{r['gtype']}-") for r in records)
    battery_count = all(str(r["battery_id"]).split("-")[-1].isdigit() and
                        int(str(r["battery_id"]).split("-")[-1]) <=
                        int(battery_cfg[r["gtype"]]["n"]) for r in records)
    battery_overlap = all(_overlap(v) for v in by_battery.values())
    soc_pass = True
    charge_pass = True
    for trip, record in zip(state.trips, records):
        e = float(evaluate_route_cached(*_key(trip)).total_route_energy_kwh)
        soc = 1.0 - e / float(gt[trip.gtype]["Euse"])
        soc_pass &= abs(float(record["soc_after"]) - soc) <= TOL and soc >= -TOL
        expected_ch = charge_time(float(battery_cfg[trip.gtype]["t_full"]), max(0.0, soc))
        charge_pass &= abs(float(record["charge_time_s"]) - expected_ch) <= TOL
    metrics = {
        "WTD": float(recomputed_wtd), "Cmax_s": float(recomputed_cmax),
        "total_energy_kwh": float(recomputed_energy), "n_trips": float(len(records))
    }
    solver_metrics = dict(schedule.metrics)
    consistency = all(abs(metrics[k] - float(solver_metrics.get(k, math.nan))) <=
                      (TOL if k != "n_trips" else 0.0) for k in metrics)
    checks = {
        "all_boxes_delivered_once": len(expected_ids) == expected_box_count and missing == 0 and duplicate == 0,
        "missing_boxes": missing == 0, "duplicate_boxes": duplicate == 0,
        "no_split_boxes": split == 0, "unknown_boxes": unknown == 0,
        "mass_pass": mass_pass, "volume_pass": volume_pass,
        "energy_pass": energy_pass, "return_reserve_pass": reserve_pass,
        "route_energy_recomputed": route_energy_consistent and route_pass,
        "delivery_recomputed": delivery_recomputed,
        "first_deadlines_pass": first_pass, "medical_deadlines_pass": medical_pass,
        "uav_type_pass": uav_type, "uav_overlap_zero": uav_overlap,
        "battery_type_pass": battery_type, "battery_count_pass": battery_count,
        "battery_overlap_zero": battery_overlap, "soc_pass": soc_pass,
        "charge_pass": charge_pass, "charge_before_reuse_pass": battery_overlap,
        "solver_validator_consistent": consistency,
    }
    return {
        "phase": "Q2-E", "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "metrics": metrics,
        "solver_metrics": solver_metrics, "n_trips": len(records),
        "n_boxes": len(expected_ids), "delivered_records": len(delivered),
        "solver_status": schedule.solver_status,
    }
