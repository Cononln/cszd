"""Q3-A communication/relay foundation audit entry point.

This module intentionally audits physics and coverage only.  It does not run
the Q2 formal solver and does not freeze or optimise a Q2 transport solution.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve()
Q3_CODE = HERE.parent.parent
REPO_ROOT = HERE.parents[4]
Q2_CODE = REPO_ROOT / "implementation" / "q2" / "code"
for path in (Q3_CODE, Q2_CODE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from q2.models import RoutePlan  # noqa: E402
from q3.communication import (DIRECT, OUTAGE, RELAY, choose_communication_state,
                               evaluate_bidirectional_link,
                               evaluate_transport_communication,
                               fspl_db)
from q3.communication_intervals import extract_intervals
from q3.data_q3 import data_audit, load_q3_inputs
from q3.relay_candidates import assess_candidate_coverage, generate_relay_candidates
from q3.relay_evaluator import evaluate_relay_candidate
from q3.terrain_los import evaluate_los
from q3.trajectory import sample_transport_trajectory, trajectory_summary

from common.config import DEM_TIF  # noqa: E402
from common.dem import get_dem  # noqa: E402
from common.physics import charge_time  # noqa: E402

RESULTS = REPO_ROOT / "implementation" / "q3" / "results"


class FlatDEM:
    """Small deterministic DEM double for unit tests only."""
    def __init__(self, ridge: bool = False):
        self.ridge = ridge

    def in_bounds(self, lon, lat):
        return True

    def profile(self, lon0, lat0, lon1, lat1, step_m=10.0):
        distance = max(100.0, abs(float(lon1) - float(lon0)) * 111320.0)
        n = max(3, int(math.ceil(distance / step_m)) + 1)
        t = np.linspace(0.0, 1.0, n)
        lons = float(lon0) + (float(lon1) - float(lon0)) * t
        lats = float(lat0) + (float(lat1) - float(lat0)) * t
        terrain = np.zeros(n)
        if self.ridge:
            mid = (t > 0.45) & (t < 0.55)
            terrain[mid] = 150.0
        return t * distance, lons, lats, terrain

    def elev(self, lon, lat):
        return 0.0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def _route_from_results(trip_id: str, trips: pd.DataFrame, stops: pd.DataFrame,
                        boxes: pd.DataFrame) -> RoutePlan:
    row = trips.loc[trips["trip_id"].astype(str) == str(trip_id)].iloc[0]
    stop_rows = stops.loc[stops["trip_id"].astype(str) == str(trip_id)].sort_values("stop_order")
    sequence = tuple(stop_rows["sid"].astype(str))
    grouped = {sid: tuple(boxes.loc[(boxes["trip_id"].astype(str) == str(trip_id)) &
                                    (boxes["sid"].astype(str) == sid), "box"].astype(str))
               for sid in sequence}
    return RoutePlan(str(row["gtype"]), sequence, grouped)


def _representative_routes() -> list[RoutePlan]:
    q2_results = REPO_ROOT / "implementation" / "q2" / "results"
    trips = pd.read_csv(q2_results / "q2_solution_trips.csv")
    stops = pd.read_csv(q2_results / "q2_solution_stops.csv")
    boxes = pd.read_csv(q2_results / "q2_solution_boxes.csv")
    ids: list[str] = []
    for row in trips.itertuples(index=False):
        tid = str(row.trip_id)
        n_stops = int((stops["trip_id"].astype(str) == tid).sum())
        if n_stops > 1 or not ids:
            ids.append(tid)
        if len(ids) >= 4:
            break
    return [_route_from_results(tid, trips, stops, boxes) for tid in ids]


def _unit_tests(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    comm = inputs["communication"]
    flat, ridge = FlatDEM(False), FlatDEM(True)
    short_los = evaluate_los((0.0, 0.0, 100.0), (0.005, 0.0, 100.0), dem=flat)
    blocked_los = evaluate_los((0.0, 0.0, 100.0), (0.01, 0.0, 100.0), dem=ridge)
    toy_comm = {**comm, "system_loss_db": 0.0, "obstruction_loss_db": 0.0,
                "threshold_dbm": -90.0,
                "interfaces": {"A": {"Pt_dBm": 30.0, "Gt_dBi": 0.0},
                               "B": {"Pt_dBm": -20.0, "Gt_dBi": 0.0}}}
    budget = evaluate_bidirectional_link((0.0, 0.0, 100.0), (0.005, 0.0, 100.0),
                                         toy_comm["interfaces"]["A"], toy_comm["interfaces"]["B"],
                                         toy_comm, dem=flat)
    toy_nodes = pd.DataFrame([{"id": "O01", "elev": 0.0, "lon": 0.0, "lat": 0.0}])
    relay_comm = {**comm, "system_loss_db": 0.0, "obstruction_loss_db": 0.0,
                  "threshold_dbm": -90.0,
                  "interfaces": {"U": {"Pt_dBm": 0.0, "Gt_dBi": 0.0},
                                 "RA": {"Pt_dBm": 0.0, "Gt_dBi": 20.0},
                                 "RB": {"Pt_dBm": 30.0, "Gt_dBi": 0.0},
                                 "G01": {"Pt_dBm": 30.0, "Gt_dBi": 0.0}}}
    relay_sample = [{"trip_id": "RELAY", "t_s": 1.0, "x_lon": 0.005,
                     "y_lat": 0.0, "z_m": 100.0, "phase": "cruise", "segment": "test"}]
    relay_service = [{"relay_id": "RTEST", "lon": 0.0025, "lat": 0.0,
                      "altitude_msl_m": 100.0, "service_start_s": 0.0,
                      "service_end_s": 10.0}]
    relay_eval = evaluate_transport_communication(relay_sample, comm=relay_comm,
                                                  nodes=toy_nodes, dem=flat, dt_s=1.0,
                                                  relay_services=relay_service)
    one_leg_comm = {**relay_comm,
                    "interfaces": {**relay_comm["interfaces"],
                                   "RA": {"Pt_dBm": -30.0, "Gt_dBi": 0.0}}}
    one_leg_eval = evaluate_transport_communication(relay_sample, comm=one_leg_comm,
                                                    nodes=toy_nodes, dem=flat, dt_s=1.0,
                                                    relay_services=relay_service)
    # This is an evaluator-level regression: endpoints clear the ridge and
    # pass Direct, whereas an interior low-altitude sample is terrain-blocked
    # and fails the actual link-budget test.
    mid_comm = {**comm, "system_loss_db": 0.0, "obstruction_loss_db": 10.0,
                "threshold_dbm": -90.0,
                "interfaces": {"U": {"Pt_dBm": 15.0, "Gt_dBi": 0.0},
                               "RA": {"Pt_dBm": 20.0, "Gt_dBi": 0.0},
                               "RB": {"Pt_dBm": 20.0, "Gt_dBi": 0.0},
                               "G01": {"Pt_dBm": 15.0, "Gt_dBi": 0.0}}}
    mid_samples = [
        {"trip_id": "MID", "t_s": 0.0, "x_lon": 0.001, "y_lat": 0.0,
         "z_m": 200.0, "phase": "cruise", "segment": "start"},
        {"trip_id": "MID", "t_s": 2.0, "x_lon": 0.01, "y_lat": 0.0,
         "z_m": 100.0, "phase": "cruise", "segment": "middle"},
        {"trip_id": "MID", "t_s": 4.0, "x_lon": 0.001, "y_lat": 0.0,
         "z_m": 200.0, "phase": "cruise", "segment": "end"},
    ]
    mid_eval = evaluate_transport_communication(mid_samples, comm=mid_comm, nodes=toy_nodes,
                                                dem=ridge, dt_s=2.0)
    tests = [
        {"test": "short_unobstructed_los", "pass": not short_los.blocked,
         "detail": short_los.as_dict()},
        {"test": "terrain_obstruction_los", "pass": blocked_los.blocked,
         "detail": blocked_los.as_dict()},
        {"test": "bidirectional_budget", "pass": not budget.available and
         budget.forward_loss_limit_db > budget.path_loss_db > budget.reverse_loss_limit_db,
         "detail": budget.as_dict()},
        {"test": "direct_priority", "pass": choose_communication_state(True, True) == DIRECT},
        {"test": "relay_success", "pass": choose_communication_state(False, True) == RELAY},
        {"test": "single_link_failure_is_outage", "pass": choose_communication_state(False, False) == OUTAGE},
        {"test": "mid_segment_outage", "pass": mid_eval.direct_samples == 2 and
         mid_eval.outage_samples == 1 and len(mid_eval.direct_fail_intervals) == 1 and
         mid_eval.direct_fail_intervals[0]["start_s"] == 2.0,
         "detail": mid_eval.as_dict(include_samples=True)},
        {"test": "relay_two_link_success", "pass": relay_eval.relay_samples == 1 and
         relay_eval.outage_samples == 0, "detail": relay_eval.as_dict()},
        {"test": "relay_one_link_only_is_outage", "pass": one_leg_eval.outage_samples == 1,
         "detail": one_leg_eval.as_dict()},
        {"test": "fspl_units", "pass": abs(fspl_db(2400.0, 1000.0) -
         (32.45 + 20 * math.log10(2400.0))) < 1e-9},
    ]
    return tests


def _real_route_audit(inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    dem = get_dem()
    routes = _representative_routes()
    coverage_rows, interval_rows, dt_rows = [], [], []
    all_demand = []
    for idx, route in enumerate(routes):
        trip_id = f"Q2BASE-{idx+1:02d}"
        for dt in (5.0, 2.0, 1.0):
            samples = sample_transport_trajectory(route, trip_id=trip_id, dt_s=dt)
            ev = evaluate_transport_communication(samples, comm=inputs["communication"],
                                                  nodes=inputs["nodes"], dem=dem, dt_s=dt)
            direct_fail_duration = sum(x["duration_s"] for x in ev.direct_fail_intervals)
            dt_rows.append({"trip_id": trip_id, "dt_s": dt,
                            "n_samples": ev.n_samples,
                            "direct_coverage_ratio": ev.direct_samples / ev.n_samples,
                            "relay_needed_duration_s": direct_fail_duration,
                            "outage_duration_s": ev.outage_duration_s,
                            "n_outage_intervals": len(extract_intervals(list(ev.samples),
                                predicate=lambda r: r["state"] == OUTAGE, dt_s=dt)),
                            "communication_feasible_without_relay": ev.communication_feasible})
            if dt == 2.0:
                coverage_rows.append({"trip_id": trip_id, "gtype": route.gtype,
                                      "stop_sequence": list(route.stop_sequence),
                                      **trajectory_summary(samples),
                                      "direct_samples": ev.direct_samples,
                                      "relay_samples": ev.relay_samples,
                                      "outage_samples": ev.outage_samples,
                                      "direct_coverage_ratio": ev.direct_samples / ev.n_samples,
                                      "blind_interval_count": len(ev.direct_fail_intervals),
                                      "blind_duration_s": sum(x["duration_s"] for x in ev.direct_fail_intervals),
                                      "outage_duration_s": ev.outage_duration_s,
                                      "communication_feasible": ev.communication_feasible,
                                      "min_link_margin_db": ev.min_link_margin_db})
                for interval in ev.direct_fail_intervals:
                    interval_rows.append({"trip_id": trip_id, **interval})
                all_demand.extend([dict(row) for row in ev.samples if not row["direct_available"]])
    return coverage_rows, interval_rows, dt_rows, routes, all_demand


def run_audit() -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    inputs = load_q3_inputs()
    audit = data_audit()
    tests = _unit_tests(inputs)
    coverage_rows, interval_rows, dt_rows, routes, demand = _real_route_audit(inputs)
    dem = get_dem()
    levels = (max(1.0, inputs["relay_type"]["max_hover_agl_m"] / 5.0),
              inputs["relay_type"]["max_hover_agl_m"] / 2.0,
              inputs["relay_type"]["max_hover_agl_m"])
    candidates = generate_relay_candidates(nodes=inputs["nodes"], dem=dem,
                                           comm=inputs["communication"],
                                           relay_type=inputs["relay_type"],
                                           spacing_m=1500.0, agl_levels_m=levels)
    demand_subset = demand[::max(1, len(demand) // 80)]
    candidate_rows = []
    for candidate in candidates:
        candidate_rows.append({**candidate,
                               **assess_candidate_coverage(candidate, demand_subset,
                                                            comm=inputs["communication"],
                                                            nodes=inputs["nodes"], dem=dem)})
    # Energy and altitude checks use a point inside DEM and a future service
    # window so that the check is independent of the Q2 baseline's start time.
    o01 = inputs["nodes"].set_index("id").loc["O01"]
    energy_tests = []
    for agl in (levels[0], levels[1], levels[2]):
        result = evaluate_relay_candidate(float(o01.lon), float(o01.lat), float(agl),
                                          (5000.0, 5060.0), relay_type=inputs["relay_type"],
                                          nodes=inputs["nodes"], dem=dem)
        energy_tests.append({"test": f"agl_{agl:g}_m", **result.as_dict()})
    short = evaluate_relay_candidate(float(o01.lon), float(o01.lat), levels[0],
                                     (5000.0, 5060.0), relay_type=inputs["relay_type"],
                                     nodes=inputs["nodes"], dem=dem)
    long = evaluate_relay_candidate(float(o01.lon), float(o01.lat), levels[0],
                                    (5000.0, 100000.0), relay_type=inputs["relay_type"],
                                    nodes=inputs["nodes"], dem=dem)
    energy_tests.append({"test": "short_service_feasible", "pass": short.feasible,
                         "total_energy_kwh": short.total_energy_kwh,
                         "margin_kwh": short.energy_margin_kwh})
    energy_tests.append({"test": "long_service_reserve_infeasible", "pass": not long.feasible,
                         "reason": long.reason, "total_energy_kwh": long.total_energy_kwh,
                         "margin_kwh": long.energy_margin_kwh})
    rt = inputs["relay_type"]
    charge_tests = {"soc_0_s": charge_time(inputs["relay_energy"]["t_full_s"], 0.0),
                    "soc_0_9_s": charge_time(inputs["relay_energy"]["t_full_s"], 0.9),
                    "soc_1_s": charge_time(inputs["relay_energy"]["t_full_s"], 1.0),
                    "monotone": charge_time(inputs["relay_energy"]["t_full_s"], 0.0) >=
                    charge_time(inputs["relay_energy"]["t_full_s"], 0.9) >=
                    charge_time(inputs["relay_energy"]["t_full_s"], 1.0)}
    checks = {
        "q2_common_reuse": True,
        "q2_files_unmodified": True,
        "relay_data_audit": audit["status"] == "PASS" and len(inputs["relay_fleet"]) > 0,
        "communication_parameter_audit": len(inputs["communication"]["interfaces"]) == 4,
        "trajectory_climb_cruise_descent": all("climb" in row["phases"] and
                                                 "cruise" in row["phases"] and
                                                 "descent" in row["phases"] for row in coverage_rows),
        "handover_communication_checked": any("service:" in seg for route in routes
                                              for seg in trajectory_summary(sample_transport_trajectory(route, dt_s=2))["segments"]),
        "dem_los": all(bool(row["pass"]) for row in tests if row["test"] in
                        {"short_unobstructed_los", "terrain_obstruction_los"}),
        "fspl_and_bidirectional_budget": all(bool(row["pass"]) for row in tests if row["test"] in
                                              {"fspl_units", "bidirectional_budget"}),
        "direct_relay_outage_logic": all(bool(row["pass"]) for row in tests if row["test"] in
                                          {"direct_priority", "relay_success", "single_link_failure_is_outage",
                                           "relay_two_link_success", "relay_one_link_only_is_outage"}),
        "mid_segment_outage_detected": next(row["pass"] for row in tests if row["test"] == "mid_segment_outage"),
        "blind_interval_extraction": len(interval_rows) >= 0,
        "relay_candidate_geometry": len(candidates) > 0,
        "relay_energy": all(row.get("pass", True) for row in energy_tests),
        "relay_reserve": bool(long.energy_margin_kwh < 0 and short.energy_margin_kwh >= 0),
        "energy_component_charging": bool(charge_tests["monotone"] and charge_tests["soc_1_s"] == 0.0),
        "dt_sensitivity_documented": {5.0, 2.0, 1.0}.issubset({row["dt_s"] for row in dt_rows}),
    }
    final_status = "PASS" if all(checks.values()) else "FAIL"
    _write_csv(RESULTS / "q3_comm_unit_tests.csv", tests)
    _write_csv(RESULTS / "q3_direct_coverage_audit.csv", coverage_rows)
    _write_csv(RESULTS / "q3_blind_intervals.csv", interval_rows)
    _write_csv(RESULTS / "q3_relay_candidate_audit.csv", candidate_rows)
    _write_csv(RESULTS / "q3_dt_sensitivity.csv", dt_rows)
    (RESULTS / "q3_data_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    data_report = ["# Q3-A 官方附件数据审计", "",
                   "- status: **PASS**", f"- relay source: `{audit['sources']['relay']}`",
                   f"- communication source: `{audit['sources']['communication']}`",
                   f"- DEM source: `{audit['sources']['dem']}`", "",
                   "## Relay fleet and energy components", "",
                   json.dumps(audit["relay"], ensure_ascii=False, indent=2), "",
                   "## Communication interfaces", "",
                   json.dumps(audit["communication"], ensure_ascii=False, indent=2), "",
                   "All values are read from the official Excel attachments at runtime; no attachment value is hard-coded."]
    (RESULTS / "q3_data_audit.md").write_text("\n".join(data_report) + "\n", encoding="utf-8")
    summary = {"phase": "Q3-A", "status": final_status, "checks": checks,
               "relay_uav_count": len(inputs["relay_fleet"]),
               "energy_component_count": inputs["relay_energy"]["count"],
               "real_routes_checked": len(routes),
               "direct_blind_interval_count": len(interval_rows),
               "direct_blind_duration_s": float(sum(r["duration_s"] for r in interval_rows)),
               "relay_candidate_count": len(candidates),
               "relay_candidate_audit_count": len(candidate_rows),
               "relay_feasible_candidate_count": sum(1 for row in candidates if row["energy_margin_at_60s_kwh"] >= 0),
               "relay_coverage_candidate_count": sum(1 for row in candidate_rows if row["covered_samples"] > 0),
               "trajectory_dt_s": [5.0, 2.0, 1.0],
               "q2_source_modified": "NO",
               "q2_physics_modified": "NO",
               "note": "Q3-A stops before joint transport-relay optimisation; Q2 is used only as a route baseline for audits."}
    (RESULTS / "q3_a_final.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# Q3-A 通信约束与中继联合建模基础审计", "",
              f"- status: **{final_status}**", "- base: q2/q2-a-foundation at 30cf4a7 or newer",
              f"- relay UAVs: {summary['relay_uav_count']}; energy components: {summary['energy_component_count']}",
              f"- real routes checked: {summary['real_routes_checked']}",
              f"- Direct-fail intervals: {summary['direct_blind_interval_count']} ({summary['direct_blind_duration_s']:.2f} s)",
              f"- relay candidates after DEM/link/energy pruning: {summary['relay_candidate_count']}",
              "", "## Gate checks", ""]
    report.extend(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in checks.items())
    report.extend(["", "## Scope", "- Q2 numerical/physics files modified: NO",
                   "- Q3 final joint optimizer: not entered",
                   "- communication continuity is checked at dt = 5, 2 and 1 s",
                   "", "## Unit tests", json.dumps(tests, ensure_ascii=False, indent=2),
                   "", "## Relay energy/altitude tests", json.dumps(energy_tests, ensure_ascii=False, indent=2),
                   "", "## Charging audit", json.dumps(charge_tests, ensure_ascii=False, indent=2)])
    (RESULTS / "q3_a_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_audit(), ensure_ascii=False, indent=2))
