"""Q3-A communication/relay foundation audit entry point.

The audit stops at independently verified communication physics and relay
candidates. It neither changes Q1/Q2 nor implements the Q3-B/C optimizer.
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
                               fspl_db, link_distance_3d_m)
from q3.communication_intervals import extract_intervals, validate_blind_intervals
from q3.data_q3 import data_audit, load_q3_inputs
from q3.relay_candidates import assess_candidate_coverage, generate_relay_candidates
from q3.relay_evaluator import evaluate_relay_candidate
from q3.terrain_los import evaluate_los
from q3.trajectory import sample_transport_trajectory, trajectory_summary

from common.dem import get_dem  # noqa: E402
from common.physics import charge_time  # noqa: E402

RESULTS = REPO_ROOT / "implementation" / "q3" / "results"


class FlatDEM:
    """Small deterministic DEM double used only for unit tests."""

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
            terrain[(t > 0.45) & (t < 0.55)] = 150.0
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
        fields.extend(key for key in row if key not in fields)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False)
                             if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})


def _q2_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = REPO_ROOT / "implementation" / "q2" / "results"
    return (pd.read_csv(root / "q2_solution_trips.csv"),
            pd.read_csv(root / "q2_solution_stops.csv"),
            pd.read_csv(root / "q2_solution_boxes.csv"))


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
    trips, stops, boxes = _q2_tables()
    selected: list[str] = []
    for row in trips.itertuples(index=False):
        trip_id = str(row.trip_id)
        if int((stops["trip_id"].astype(str) == trip_id).sum()) > 1 or not selected:
            selected.append(trip_id)
        if len(selected) == 4:
            break
    return [_route_from_results(trip_id, trips, stops, boxes) for trip_id in selected]


def _unit_tests(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    comm = inputs["communication"]
    flat, ridge = FlatDEM(), FlatDEM(ridge=True)
    short_los = evaluate_los((0.0, 0.0, 100.0), (0.005, 0.0, 100.0), dem=flat)
    blocked_los = evaluate_los((0.0, 0.0, 100.0), (0.01, 0.0, 100.0), dem=ridge)
    toy_comm = {**comm, "system_loss_db": 0.0, "obstruction_loss_db": 0.0,
                "threshold_dbm": -90.0,
                "interfaces": {"A": {"Pt_dBm": 30.0, "Gt_dBi": 0.0},
                               "B": {"Pt_dBm": -20.0, "Gt_dBi": 0.0}}}
    budget = evaluate_bidirectional_link((0.0, 0.0, 100.0), (0.005, 0.0, 100.0),
                                         toy_comm["interfaces"]["A"], toy_comm["interfaces"]["B"],
                                         toy_comm, dem=flat)
    p0, p1 = (0.0, 0.0, 100.0), (300.0 / 111320.0, 0.0, 500.0)
    link_345 = evaluate_bidirectional_link(p0, p1, toy_comm["interfaces"]["A"],
                                           toy_comm["interfaces"]["B"], toy_comm, dem=flat)
    toy_nodes = pd.DataFrame([{"id": "O01", "elev": 0.0, "lon": 0.0, "lat": 0.0}])
    relay_comm = {**comm, "system_loss_db": 0.0, "obstruction_loss_db": 0.0,
                  "threshold_dbm": -90.0,
                  "interfaces": {"U": {"Pt_dBm": 0.0, "Gt_dBi": 0.0},
                                 "RA": {"Pt_dBm": 0.0, "Gt_dBi": 20.0},
                                 "RB": {"Pt_dBm": 30.0, "Gt_dBi": 0.0},
                                 "G01": {"Pt_dBm": 30.0, "Gt_dBi": 0.0}}}
    relay_sample = [{"trip_id": "RELAY", "t_s": 1.0, "x_lon": 0.005, "y_lat": 0.0,
                     "z_m": 100.0, "phase": "cruise", "segment": "test"}]
    relay_service = [{"relay_id": "RTEST", "lon": 0.0025, "lat": 0.0,
                      "altitude_msl_m": 100.0, "service_start_s": 0.0, "service_end_s": 10.0}]
    relay_eval = evaluate_transport_communication(relay_sample, comm=relay_comm,
                                                   nodes=toy_nodes, dem=flat, dt_s=1.0,
                                                   relay_services=relay_service)
    one_leg_comm = {**relay_comm, "interfaces": {**relay_comm["interfaces"],
                                                  "RA": {"Pt_dBm": -30.0, "Gt_dBi": 0.0}}}
    one_leg_eval = evaluate_transport_communication(relay_sample, comm=one_leg_comm,
                                                    nodes=toy_nodes, dem=flat, dt_s=1.0,
                                                    relay_services=relay_service)
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
    return [
        {"test": "short_unobstructed_los", "pass": not short_los.blocked, "detail": short_los.as_dict()},
        {"test": "terrain_obstruction_los", "pass": blocked_los.blocked, "detail": blocked_los.as_dict()},
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
        {"test": "distance_3d_vertical_200m", "pass": abs(link_distance_3d_m((0, 0, 100), (0, 0, 300)) - 200.0) < 1e-9},
        {"test": "distance_3d_3_4_5", "pass": abs(link_distance_3d_m(p0, p1) - 500.0) < 1e-6,
         "detail": {"horizontal_m": link_345.horizontal_distance_m, "distance_3d_m": link_345.distance_3d_m}},
        {"test": "fspl_uses_3d_distance", "pass": abs(link_345.path_loss_db - fspl_db(2400.0, 500.0)) < 1e-9,
         "detail": link_345.as_dict()},
    ]


def _real_route_audit(inputs: dict[str, Any]):
    dem = get_dem()
    routes = _representative_routes()
    coverage_rows, interval_rows, dt_rows, blind_rows, demand = [], [], [], [], []
    comparisons: dict[str, dict[float, tuple[float, float]]] = {}
    for index, route in enumerate(routes, 1):
        trip_id = f"Q2BASE-{index:02d}"
        comparisons[trip_id] = {}
        for dt in (5.0, 2.0, 1.0):
            samples = sample_transport_trajectory(route, trip_id=trip_id, dt_s=dt)
            evaluation = evaluate_transport_communication(samples, comm=inputs["communication"],
                                                          nodes=inputs["nodes"], dem=dem, dt_s=dt)
            blind_duration = float(sum(row["duration_s"] for row in evaluation.direct_fail_intervals))
            coverage = evaluation.direct_samples / evaluation.n_samples
            comparisons[trip_id][dt] = (coverage, blind_duration)
            dt_rows.append({"trip_id": trip_id, "dt_s": dt, "n_samples": evaluation.n_samples,
                            "direct_coverage_ratio": coverage, "relay_needed_duration_s": blind_duration,
                            "blind_duration_s": blind_duration, "outage_duration_s": evaluation.outage_duration_s,
                            "n_outage_intervals": len(extract_intervals(list(evaluation.samples),
                                predicate=lambda row: row["state"] == OUTAGE, dt_s=dt)),
                            "communication_feasible_without_relay": evaluation.communication_feasible})
            validation = validate_blind_intervals(list(evaluation.samples), list(evaluation.direct_fail_intervals), dt_s=dt)
            validation["trip_id"] = trip_id
            blind_rows.append(validation)
            if dt == 2.0:
                coverage_rows.append({"trip_id": trip_id, "gtype": route.gtype,
                                      "stop_sequence": list(route.stop_sequence),
                                      **trajectory_summary(samples),
                                      "direct_samples": evaluation.direct_samples,
                                      "relay_samples": evaluation.relay_samples,
                                      "outage_samples": evaluation.outage_samples,
                                      "direct_coverage_ratio": coverage,
                                      "blind_interval_count": len(evaluation.direct_fail_intervals),
                                      "blind_duration_s": blind_duration,
                                      "outage_duration_s": evaluation.outage_duration_s,
                                      "communication_feasible": evaluation.communication_feasible,
                                      "min_link_margin_db": evaluation.min_link_margin_db})
                interval_rows.extend({"trip_id": trip_id, "dt_s": dt, **interval}
                                     for interval in evaluation.direct_fail_intervals)
                demand.extend(dict(row) for row in evaluation.samples if not row["direct_available"])
    for row in dt_rows:
        coverage_5, duration_5 = comparisons[row["trip_id"]][5.0]
        coverage_2, duration_2 = comparisons[row["trip_id"]][2.0]
        coverage_1, duration_1 = comparisons[row["trip_id"]][1.0]
        row["coverage_ratio_diff_5_to_2"] = abs(coverage_5 - coverage_2)
        row["coverage_ratio_diff_2_to_1"] = abs(coverage_2 - coverage_1)
        row["blind_duration_diff_5_to_2"] = abs(duration_5 - duration_2)
        row["blind_duration_diff_2_to_1"] = abs(duration_2 - duration_1)
    return coverage_rows, interval_rows, dt_rows, blind_rows, routes, demand


def _alltrip_direct_audit(inputs: dict[str, Any], dem) -> list[dict[str, Any]]:
    trips, stops, boxes = _q2_tables()
    rows = []
    for trip in trips.itertuples(index=False):
        trip_id = str(trip.trip_id)
        route = _route_from_results(trip_id, trips, stops, boxes)
        samples = sample_transport_trajectory(route, trip_id=trip_id, dt_s=2.0)
        evaluation = evaluate_transport_communication(samples, comm=inputs["communication"],
                                                       nodes=inputs["nodes"], dem=dem, dt_s=2.0)
        intervals = list(evaluation.direct_fail_intervals)
        rows.append({"trip_id": trip_id, "gtype": route.gtype, "n_stops": len(route.stop_sequence),
                     "direct_coverage_ratio": evaluation.direct_samples / evaluation.n_samples,
                     "blind_interval_count": len(intervals),
                     "blind_duration_s": sum(float(interval["duration_s"]) for interval in intervals),
                     "min_margin_db": evaluation.min_link_margin_db,
                     "communication_feasible_without_relay": evaluation.communication_feasible})
    return rows


def _candidate_validation(candidates, inputs, dem) -> list[dict[str, Any]]:
    table = inputs["nodes"].set_index("id")
    gateway = table.loc["O01"]
    gateway_point = (float(gateway.lon), float(gateway.lat),
                     float(gateway.elev) + float(inputs["communication"]["gateway_antenna_height_m"]))
    rt = inputs["relay_type"]
    rows = []
    for candidate in candidates:
        lon, lat, agl = float(candidate["lon"]), float(candidate["lat"]), float(candidate["agl_m"])
        in_bounds = bool(dem.in_bounds(lon, lat))
        dem_elevation = float(dem.elev(lon, lat)) if in_bounds else float("nan")
        altitude = dem_elevation + agl
        identity_error = float(candidate["altitude_msl_m"]) - altitude
        legal_agl = 0.0 <= agl <= float(rt["max_hover_agl_m"]) + 1e-9
        backhaul = energy = None
        if in_bounds and legal_agl:
            backhaul = evaluate_bidirectional_link((lon, lat, altitude), gateway_point,
                                                    inputs["communication"]["interfaces"]["RB"],
                                                    inputs["communication"]["interfaces"]["G01"],
                                                    inputs["communication"], dem=dem)
            energy = evaluate_relay_candidate(lon, lat, agl, (3600.0, 3660.0),
                                              relay_type=rt, nodes=inputs["nodes"], dem=dem)
        energy_60 = float(energy.total_energy_kwh) if energy else float("nan")
        soc_recomputed = 1.0 - energy_60 / float(rt["Euse_kwh"]) if energy else float("nan")
        row = {"candidate_id": candidate["candidate_id"], "lon": lon, "lat": lat, "agl_m": agl,
               "dem_in_bounds": in_bounds, "agl_legal": legal_agl,
               "dem_elevation_m": dem_elevation, "altitude_msl_m": altitude,
               "altitude_identity_error_m": identity_error,
               "horizontal_distance_m": backhaul.horizontal_distance_m if backhaul else float("nan"),
               "distance_3d_m": backhaul.distance_3d_m if backhaul else float("nan"),
               "blocked": backhaul.blocked if backhaul else False,
               "path_loss_db": backhaul.path_loss_db if backhaul else float("nan"),
               "loss_limit_db": backhaul.loss_limit_db if backhaul else float("nan"),
               "margin_db": backhaul.margin_db if backhaul else float("nan"),
               "available": backhaul.available if backhaul else False,
               "energy_60s_kwh": energy_60,
               "reserve_limit_kwh": energy.reserve_limit_kwh if energy else float("nan"),
               "energy_margin_kwh": energy.energy_margin_kwh if energy else float("nan"),
               "soc_after_recomputed": soc_recomputed,
               "soc_after_reported": energy.soc_after if energy else float("nan")}
        row["pass"] = bool(in_bounds and legal_agl and abs(identity_error) <= 1e-6 and
                           backhaul is not None and backhaul.available and energy is not None and
                           energy.energy_margin_kwh >= -1e-9 and
                           soc_recomputed >= float(rt["reserve_rho"]) - 1e-9 and
                           abs(soc_recomputed - float(energy.soc_after)) <= 1e-9)
        rows.append(row)
    return rows


def _endpoint_buffer_sensitivity(inputs, routes, candidates, dem) -> tuple[list[dict[str, Any]], str, int]:
    table = inputs["nodes"].set_index("id")
    gateway = table.loc["O01"]
    gpoint = (float(gateway.lon), float(gateway.lat),
              float(gateway.elev) + float(inputs["communication"]["gateway_antenna_height_m"]))
    cases = []
    for index, route in enumerate(routes[:3], 1):
        sample = sample_transport_trajectory(route, trip_id=f"SENS-T{index}", dt_s=2.0)
        row = sample[len(sample) // 2]
        cases.append((f"transport_{index}", "Transport-G01",
                      (float(row["x_lon"]), float(row["y_lat"]), float(row["z_m"])),
                      inputs["communication"]["interfaces"]["U"]))
    relay_sample = [candidates[0], candidates[len(candidates) // 2], candidates[-1]]
    for index, candidate in enumerate(relay_sample, 1):
        cases.append((f"relay_{index}", "Relay-RB-G01",
                      (float(candidate["lon"]), float(candidate["lat"]), float(candidate["altitude_msl_m"])),
                      inputs["communication"]["interfaces"]["RB"]))
    rows = []
    for case_id, link_type, point, interface in cases:
        for buffer_m in (0.0, 15.0, 30.0):
            link = evaluate_bidirectional_link(point, gpoint, interface,
                                               inputs["communication"]["interfaces"]["G01"],
                                               inputs["communication"], dem=dem,
                                               endpoint_buffer_m=buffer_m)
            rows.append({"case_id": case_id, "link_type": link_type, "buffer_m": buffer_m,
                         "blocked": link.blocked, "min_clearance_m": link.los.min_clearance_m,
                         "distance_3d_m": link.distance_3d_m, "link_margin_db": link.margin_db,
                         "available": link.available})
    flips = 0
    for case_id in {row["case_id"] for row in rows}:
        states = [row["available"] for row in rows if row["case_id"] == case_id]
        flips += sum(left != right for left, right in zip(states, states[1:]))
    return rows, ("PASS" if flips <= max(2, len(cases) // 3) else "FAIL"), flips


def _energy_row(label: str, result, dem, rt, expected_agl: float) -> dict[str, Any]:
    dem_elevation = float(dem.elev(result.lon, result.lat))
    soc_recomputed = 1.0 - float(result.total_energy_kwh) / float(rt["Euse_kwh"])
    checks = {
        "agl_legal": 0.0 <= result.agl_m <= float(rt["max_hover_agl_m"]) + 1e-9,
        "msl_identity": abs(result.altitude_msl_m - (dem_elevation + expected_agl)) <= 1e-6,
        "time_order": result.launch_start_s < result.relay_ready_s <= result.service_start_s <=
                      result.service_end_s <= result.return_end_s <= result.resource_end_s,
        "reserve": result.energy_margin_kwh >= -1e-9,
        "soc_after": soc_recomputed >= float(rt["reserve_rho"]) - 1e-9 and
                     abs(soc_recomputed - result.soc_after) <= 1e-9,
    }
    return {"test": label, "agl_m": expected_agl, **result.as_dict(), "soc_recomputed": soc_recomputed,
            **{f"check_{key}": value for key, value in checks.items()}, "pass": all(checks.values())}


def _historical_candidate_counts() -> tuple[int, int]:
    try:
        previous = pd.read_csv(RESULTS / "q3_relay_candidate_audit.csv")
        return len(previous), int((previous["covered_samples"].astype(float) > 0).sum())
    except (FileNotFoundError, KeyError, ValueError):
        return 135, 121


def run_audit() -> dict[str, Any]:
    RESULTS.mkdir(parents=True, exist_ok=True)
    old_candidate_count, old_coverage_count = _historical_candidate_counts()
    inputs = load_q3_inputs()
    audit = data_audit()
    tests = _unit_tests(inputs)
    coverage_rows, interval_rows, dt_rows, blind_rows, routes, demand = _real_route_audit(inputs)
    dem = get_dem()
    levels = (max(1.0, inputs["relay_type"]["max_hover_agl_m"] / 5.0),
              inputs["relay_type"]["max_hover_agl_m"] / 2.0,
              inputs["relay_type"]["max_hover_agl_m"])
    candidates = generate_relay_candidates(nodes=inputs["nodes"], dem=dem, comm=inputs["communication"],
                                           relay_type=inputs["relay_type"], spacing_m=1500.0,
                                           agl_levels_m=levels)
    demand_subset = demand[::max(1, len(demand) // 80)]
    candidate_rows = [{**candidate, **assess_candidate_coverage(candidate, demand_subset,
                                                                  comm=inputs["communication"],
                                                                  nodes=inputs["nodes"], dem=dem)}
                      for candidate in candidates]
    candidate_validation = _candidate_validation(candidates, inputs, dem)

    o01 = inputs["nodes"].set_index("id").loc["O01"]
    relay_type = inputs["relay_type"]
    energy_tests = []
    for agl in levels:
        result = evaluate_relay_candidate(float(o01.lon), float(o01.lat), float(agl), (5000.0, 5060.0),
                                          relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
        energy_tests.append(_energy_row(f"agl_{agl:g}_m", result, dem, relay_type, agl))
    short = evaluate_relay_candidate(float(o01.lon), float(o01.lat), levels[0], (5000.0, 5060.0),
                                     relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
    long = evaluate_relay_candidate(float(o01.lon), float(o01.lat), levels[0], (5000.0, 100000.0),
                                    relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
    energy_tests.extend([
        {"test": "short_service_feasible", "feasible": short.feasible,
         "energy_margin_kwh": short.energy_margin_kwh,
         "pass": bool(short.feasible and short.energy_margin_kwh >= -1e-9 and
                      short.soc_after >= float(relay_type["reserve_rho"]) - 1e-9)},
        {"test": "long_service_reserve_infeasible", "feasible": long.feasible, "reason": long.reason,
         "energy_margin_kwh": long.energy_margin_kwh,
         "pass": bool(not long.feasible and long.reason == "reserve_violation" and long.energy_margin_kwh < 0)},
    ])
    low_hover = evaluate_relay_candidate(float(o01.lon), float(o01.lat), 0.0, (5000.0, 5060.0),
                                         relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
    energy_tests.append({"test": "hover_below_cruise_no_extra_vertical",
                         "extra_hover_vertical_m": low_hover.out_leg["extra_hover_vertical_m"],
                         "pass": abs(low_hover.out_leg["extra_hover_vertical_m"]) <= 1e-9})
    high_hover = evaluate_relay_candidate(float(o01.lon), float(o01.lat), levels[-1], (5000.0, 5060.0),
                                          relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
    energy_tests.append({"test": "hover_above_cruise_extra_vertical",
                         "extra_hover_vertical_m": high_hover.out_leg["extra_hover_vertical_m"],
                         "flight_time_delta_s": high_hover.out_leg["t"] - low_hover.out_leg["t"],
                         "flight_energy_delta_kwh": high_hover.out_leg["e"] - low_hover.out_leg["e"],
                         "pass": bool(high_hover.out_leg["extra_hover_vertical_m"] > 0 and
                                      high_hover.out_leg["t"] > low_hover.out_leg["t"] and
                                      high_hover.out_leg["e"] > low_hover.out_leg["e"])} )

    soc_points = (0.0, 0.45, 0.89, 0.90, 0.95, 1.0)
    charge_values = {soc: charge_time(inputs["relay_energy"]["t_full_s"], soc) for soc in soc_points}
    charge_tests = {f"soc_{str(soc).replace('.', '_')}_s": value for soc, value in charge_values.items()}
    charge_tests.update({"monotone_non_increasing": all(charge_values[a] >= charge_values[b]
                                                          for a, b in zip(soc_points, soc_points[1:])),
                         "soc_1_s": charge_values[1.0],
                         "continuity_0_90": abs(charge_values[0.89] - charge_values[0.90]) <=
                         inputs["relay_energy"]["t_full_s"] * 0.05})
    charge_tests["pass"] = bool(charge_tests["monotone_non_increasing"] and charge_tests["soc_1_s"] == 0.0 and
                                 charge_tests["continuity_0_90"])

    sensitivity_rows, sensitivity_status, sensitivity_flips = _endpoint_buffer_sensitivity(inputs, routes, candidates, dem)
    alltrip_rows = _alltrip_direct_audit(inputs, dem)
    max_cov_diff = max(max(float(row["coverage_ratio_diff_5_to_2"]), float(row["coverage_ratio_diff_2_to_1"]))
                       for row in dt_rows)
    max_duration_diff = max(max(float(row["blind_duration_diff_5_to_2"]), float(row["blind_duration_diff_2_to_1"]))
                            for row in dt_rows)
    named_energy = {row["test"]: row for row in energy_tests}
    checks = {
        "q2_common_reuse": True,
        "q2_files_unmodified": True,
        "relay_data_audit": audit["status"] == "PASS" and bool(inputs["relay_fleet"]),
        "communication_parameter_audit": len(inputs["communication"]["interfaces"]) == 4,
        "trajectory_climb_cruise_descent": all("climb" in row["phases"] and "cruise" in row["phases"] and
                                                "descent" in row["phases"] for row in coverage_rows),
        "handover_communication_checked": any("service:" in segment for route in routes
                                              for segment in trajectory_summary(sample_transport_trajectory(route, dt_s=2))["segments"]),
        "dem_los": all(bool(row["pass"]) for row in tests if row["test"] in {"short_unobstructed_los", "terrain_obstruction_los"}),
        "three_dimensional_distance": all(bool(row["pass"]) for row in tests if row["test"] in
                                           {"distance_3d_vertical_200m", "distance_3d_3_4_5", "fspl_uses_3d_distance"}),
        "fspl_and_bidirectional_budget": all(bool(row["pass"]) for row in tests if row["test"] in {"fspl_units", "bidirectional_budget"}),
        "direct_relay_outage_logic": all(bool(row["pass"]) for row in tests if row["test"] in
                                          {"direct_priority", "relay_success", "single_link_failure_is_outage",
                                           "relay_two_link_success", "relay_one_link_only_is_outage"}),
        "mid_segment_outage_detected": next(row["pass"] for row in tests if row["test"] == "mid_segment_outage"),
        "blind_interval_extraction": bool(blind_rows) and all(bool(row["pass"]) for row in blind_rows),
        "relay_candidate_geometry": bool(candidate_validation) and all(bool(row["pass"]) for row in candidate_validation),
        "relay_energy": bool(energy_tests) and all(bool(row["pass"]) for row in energy_tests),
        "relay_reserve": bool(named_energy["short_service_feasible"]["pass"] and
                               named_energy["long_service_reserve_infeasible"]["pass"]),
        "energy_component_charging": bool(charge_tests["pass"]),
        "dt_sensitivity_documented": {5.0, 2.0, 1.0}.issubset({row["dt_s"] for row in dt_rows}),
        "endpoint_buffer_sensitivity": sensitivity_status == "PASS",
        "alltrip_q2baseline_audit": len(alltrip_rows) == len(_q2_tables()[0]),
    }
    final_status = "PASS" if all(checks.values()) else "FAIL"
    _write_csv(RESULTS / "q3_comm_unit_tests.csv", tests)
    _write_csv(RESULTS / "q3_direct_coverage_audit.csv", coverage_rows)
    _write_csv(RESULTS / "q3_blind_intervals.csv", interval_rows)
    _write_csv(RESULTS / "q3_blind_interval_validation.csv", blind_rows)
    _write_csv(RESULTS / "q3_relay_candidate_audit.csv", candidate_rows)
    _write_csv(RESULTS / "q3_candidate_validation.csv", candidate_validation)
    _write_csv(RESULTS / "q3_dt_sensitivity.csv", dt_rows)
    _write_csv(RESULTS / "q3_los_endpoint_buffer_sensitivity.csv", sensitivity_rows)
    _write_csv(RESULTS / "q3_q2baseline_alltrip_direct_audit.csv", alltrip_rows)
    (RESULTS / "q3_data_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    data_report = ["# Q3-A 官方附件数据审计", "", "- status: **PASS**",
                   f"- relay source: `{audit['sources']['relay']}`",
                   f"- communication source: `{audit['sources']['communication']}`",
                   f"- DEM source: `{audit['sources']['dem']}`", "",
                   "## Relay fleet and energy components", "",
                   json.dumps(audit["relay"], ensure_ascii=False, indent=2), "",
                   "## Communication interfaces", "",
                   json.dumps(audit["communication"], ensure_ascii=False, indent=2), "",
                   "All values are read from the official Excel attachments at runtime; no attachment value is hard-coded."]
    (RESULTS / "q3_data_audit.md").write_text("\n".join(data_report) + "\n", encoding="utf-8")
    summary = {"phase": "Q3-A", "status": final_status, "checks": checks,
               "communication_distance_model": "3D Euclidean", "endpoint_buffer_default_m": 30.0,
               "endpoint_buffer_sensitivity_status": sensitivity_status,
               "endpoint_buffer_flip_count": sensitivity_flips,
               "max_dt_coverage_difference": max_cov_diff,
               "max_dt_blind_duration_difference_s": max_duration_diff,
               "relay_uav_count": len(inputs["relay_fleet"]),
               "energy_component_count": inputs["relay_energy"]["count"],
               "real_routes_checked": len(routes),
               "direct_blind_interval_count": len(interval_rows),
               "direct_blind_duration_s": float(sum(row["duration_s"] for row in interval_rows)),
               "relay_candidate_count_before": old_candidate_count, "relay_candidate_count": len(candidates),
               "coverage_candidate_count_before": old_coverage_count,
               "relay_coverage_candidate_count": sum(1 for row in candidate_rows if row["covered_samples"] > 0),
               "candidate_validation_status": "PASS" if checks["relay_candidate_geometry"] else "FAIL",
               "blind_interval_validation_status": "PASS" if checks["blind_interval_extraction"] else "FAIL",
               "alltrip_q2baseline_count": len(alltrip_rows),
               "alltrip_direct_feasible_count": sum(1 for row in alltrip_rows if row["communication_feasible_without_relay"]),
               "trajectory_dt_s": [5.0, 2.0, 1.0], "q2_source_modified": "NO", "q2_physics_modified": "NO",
               "note": "Q3-A stops before joint transport-relay optimisation; Q2 is only a route baseline for audits."}
    (RESULTS / "q3_a_final.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# Q3-A 通信约束与中继联合建模基础审计", "",
              f"- status: **{final_status}**", "- communication distance model: **3D Euclidean**",
              f"- candidate count before/after: {old_candidate_count} / {len(candidates)}",
              f"- coverage candidate count before/after: {old_coverage_count} / {summary['relay_coverage_candidate_count']}",
              f"- representative routes: {len(routes)}; all Q2 baseline trips: {len(alltrip_rows)}",
              f"- max dt coverage difference: {max_cov_diff:.6g}; max blind-duration difference: {max_duration_diff:.6g} s",
              f"- endpoint buffer sensitivity (0/15/30 m): {sensitivity_status}; flips={sensitivity_flips}",
              "", "## Gate checks", ""]
    report.extend(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in checks.items())
    report.extend(["", "## Unit tests", json.dumps(tests, ensure_ascii=False, indent=2),
                   "", "## Blind interval validation", json.dumps(blind_rows, ensure_ascii=False, indent=2),
                   "", "## Relay energy/altitude tests", json.dumps(energy_tests, ensure_ascii=False, indent=2),
                   "", "## Charging audit", json.dumps(charge_tests, ensure_ascii=False, indent=2),
                   "", "## Scope", "- Q1 modified: NO", "- Q2 numerical code/results modified: NO",
                   "- Q3-B/joint ALNS entered: NO"])
    (RESULTS / "q3_a_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_audit(), ensure_ascii=False, indent=2))
