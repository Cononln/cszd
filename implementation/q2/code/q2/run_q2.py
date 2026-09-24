"""唯一正式 Q2 入口：返修后的 Q2-C → Q2-D → Q2-E 冻结验收。"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(HERE.parent))
    from q2.alns_solver import (WEIGHT_VECTORS, SeedResult, _destroy_random, _repair,
                                build_initial_state, dominates, evaluate_state, solve_formal)
    from q2.baselines import (legacy_random_neighborhood_baseline, q1_formal_structure,
                              q2_single_stop_baseline)
    from q2.exact_benchmark import run_exact_benchmarks
    from q2.models import Q2State
    from q2.normalization import METRIC_KEYS, Normalization
    from q2.route_evaluator import route_cache_info
    from q2.schedule_decoder import battery_reuse_rows, decode_schedule
    from q2.validate_q2 import validate_solution
else:
    from .alns_solver import (WEIGHT_VECTORS, SeedResult, _destroy_random, _repair,
                              build_initial_state, dominates, evaluate_state, solve_formal)
    from .baselines import (legacy_random_neighborhood_baseline, q1_formal_structure,
                            q2_single_stop_baseline)
    from .exact_benchmark import run_exact_benchmarks
    from .models import Q2State
    from .normalization import METRIC_KEYS, Normalization
    from .route_evaluator import route_cache_info
    from .schedule_decoder import battery_reuse_rows, decode_schedule
    from .validate_q2 import validate_solution

Q2_DIR = HERE.parents[1]
RESULTS = Q2_DIR / "results"
SEEDS_DEFAULT = [20260924, 20260925, 20260926, 20260927,
                 20260928, 20260929, 20260930, 20261001]


def parallel_config(cpu_count: int, seed_workers: int | None, cp_workers: int | None,
                    serial: bool) -> dict[str, Any]:
    if serial:
        return {"cpu_count": cpu_count, "seed_workers": 1, "cp_sat_workers": 1,
                "parallel_mode": False, "parallel_fallback_reason": None}
    sw = max(1, int(seed_workers if seed_workers is not None else min(4, max(1, cpu_count // 4))))
    cw = min(8, max(1, int(cp_workers if cp_workers is not None else max(1, cpu_count // sw))))
    if sw * cw > cpu_count:
        cw = max(1, cpu_count // sw)
    return {"cpu_count": cpu_count, "seed_workers": sw, "cp_sat_workers": cw,
            "parallel_mode": sw > 1 or cw > 1, "parallel_fallback_reason": None}


def _seed_worker(payload) -> SeedResult:
    seed, limit, cp_workers, iterations, norm_dict, weight_name = payload
    norm = Normalization(norm_dict["ideal"], norm_dict["nadir"], norm_dict["rho"])
    return solve_formal(seed, time_limit_s=limit, cp_workers=cp_workers, iterations=iterations,
                        normalization=norm, weight_name=weight_name)


def _run_seeds(seeds, cfg, *, time_limit, iterations, normalization):
    payloads = [(seed, time_limit, int(cfg["cp_sat_workers"]), iterations,
                 normalization.as_dict(), list(WEIGHT_VECTORS)[idx % len(WEIGHT_VECTORS)])
                for idx, seed in enumerate(seeds)]
    results, errors = [], []
    def serial():
        for payload in payloads:
            try:
                results.append(_seed_worker(payload))
            except Exception as exc:
                errors.append({"seed": payload[0], "status": "FAILED", "error": repr(exc)})
    if cfg["seed_workers"] <= 1:
        serial()
        return results, errors
    try:
        with cf.ProcessPoolExecutor(max_workers=int(cfg["seed_workers"])) as ex:
            futures = {ex.submit(_seed_worker, payload): payload[0] for payload in payloads}
            for future in cf.as_completed(futures):
                seed = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    errors.append({"seed": seed, "status": "FAILED", "error": repr(exc)})
    except (OSError, PermissionError) as exc:
        cfg["parallel_fallback_reason"] = f"ProcessPool unavailable: {type(exc).__name__}"
        cfg["seed_workers"] = 1
        cfg["parallel_mode"] = bool(cfg["cp_sat_workers"] > 1)
        serial()
    results.sort(key=lambda r: r.seed)
    return results, errors


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _structure_stats(state: Q2State) -> dict[str, float]:
    stops = [len(trip.stop_sequence) for trip in state.trips]
    return {"n_multistop_trips": float(sum(value > 1 for value in stops)),
            "max_stops": float(max(stops, default=0)),
            "mean_stops_per_trip": float(sum(stops) / len(stops) if stops else 0.0)}


def _evaluate_fixed_state(state: Q2State, cfg, limit, seed):
    started = time.perf_counter()
    schedule = decode_schedule(state, cp_workers=cfg["cp_sat_workers"],
                               time_limit_s=limit, fixed_seed=seed)
    validation = validate_solution(state, schedule)
    return schedule, validation, time.perf_counter() - started


def _anchor_normalization(cfg, *, time_limit: float) -> tuple[Normalization, list[dict[str, Any]]]:
    """Build fixed ideal/nadir bounds from actual pre-run reference solutions."""
    rng = __import__("numpy").random.default_rng(20260924)
    initial = q2_single_stop_baseline(20260924)
    pool = [("Q2_single_stop", initial),
            ("Legacy_random_neighborhood", legacy_random_neighborhood_baseline(20260924))]
    for mode in ("cheapest-delta", "deadline-first", "energy-aware", "regret-2", "new-trip"):
        partial = _destroy_random(initial, 0.18, rng)
        state = _repair(partial, rng, mode=mode)
        pool.append((f"warmup_{mode}", state))
    rows = []
    for index, (name, state) in enumerate(pool):
        schedule, validation, runtime = _evaluate_fixed_state(state, cfg, min(3.0, time_limit),
                                                                20260924 + index)
        if validation["status"] != "PASS":
            continue
        rows.append({"anchor_name": name, **{key: float(schedule.metrics[key]) for key in METRIC_KEYS},
                     **_structure_stats(state), "runtime_s": runtime})
    if not rows:
        raise RuntimeError("no feasible anchor schedule for normalization")
    # Every metric has a transparent min-oriented anchor label; all rows still
    # remain in the nadir pool to give conservative upper bounds.
    for key in METRIC_KEYS:
        best = min(rows, key=lambda row: row[key])
        best["anchor_role"] = (best.get("anchor_role", "") + f" min-{key}").strip()
    return Normalization.from_metrics(rows), rows


def _global_pareto(results: list[SeedResult], normalization: Normalization):
    candidates = []
    for result in results:
        for item in result.pareto:
            if "state" not in item or "schedule" not in item:
                continue
            candidates.append(item)
        candidates.append({"seed": result.seed, "iteration": "best", "state": result.state,
                           "schedule": result.schedule, "metrics": dict(result.metrics),
                           "solution_id": f"seed-{result.seed}-best"})
    unique = {}
    for item in candidates:
        key = tuple(round(float(item["metrics"][metric]), 8) for metric in METRIC_KEYS)
        unique.setdefault(key, item)
    candidate_rows = []
    for item in unique.values():
        candidate_rows.append({"source_seed": item["seed"], "solution_id": item["solution_id"],
                               "iteration": item.get("iteration", ""), **item["metrics"],
                               "normalized_ideal_distance": normalization.ideal_distance(item["metrics"])})
    nondominated = []
    for item in unique.values():
        if any(other is not item and dominates(other["metrics"], item["metrics"])
               for other in unique.values()):
            continue
        nondominated.append(item)
    nondominated.sort(key=lambda item: (normalization.ideal_distance(item["metrics"]),
                                        str(item["solution_id"])))
    pareto_rows = [{"source_seed": item["seed"], "solution_id": item["solution_id"],
                    "iteration": item.get("iteration", ""), **item["metrics"],
                    "normalized_ideal_distance": normalization.ideal_distance(item["metrics"])}
                   for item in nondominated]
    return nondominated, candidate_rows, pareto_rows


def _flatten_solution(state: Q2State, schedule):
    trips, stops, boxes, uavs, bats = [], [], [], [], []
    for trip, rec in zip(state.trips, schedule.trip_records):
        trips.append({key: (json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value)
                      for key, value in rec.items() if key not in {"legs", "boxes_by_stop", "delivery_by_box_s"}})
        for order, sid in enumerate(trip.stop_sequence, 1):
            stops.append({"trip_id": rec["trip_id"], "gtype": trip.gtype, "stop_order": order,
                          "sid": sid, "delivery_offset_s": rec["delivery_offset_by_sid_s"][sid],
                          "delivery_time_s": rec["start_time_s"] + rec["delivery_offset_by_sid_s"][sid]})
            for box in trip.boxes_by_stop[sid]:
                boxes.append({"trip_id": rec["trip_id"], "box": box, "sid": sid, "gtype": trip.gtype,
                              "uid": rec["uid"], "battery_id": rec["battery_id"],
                              "delivery_time_s": rec["delivery_by_box_s"][box]})
        uavs.append({"trip_id": rec["trip_id"], "uid": rec["uid"], "gtype": trip.gtype,
                     "start_time_s": rec["start_time_s"], "departure_time_s": rec["departure_time_s"],
                     "return_time_s": rec["return_time_s"]})
        bats.append({"trip_id": rec["trip_id"], "battery_id": rec["battery_id"], "gtype": trip.gtype,
                     "flight_start_s": rec["start_time_s"], "flight_end_s": rec["return_time_s"],
                     "charge_start_s": rec["charge_start_s"], "charge_end_s": rec["charge_end_s"],
                     "soc_after": rec["soc_after"], "charge_time_s": rec["charge_time_s"]})
    return trips, stops, boxes, uavs, bats


def _charge_audit():
    from common.data import load_transport_batteries
    from common.physics import charge_time
    soc_values = [0.0, .45, .89, .90, .95, 1.0]
    out, passed = {}, True
    for gtype, config in load_transport_batteries().items():
        times = [float(charge_time(config["t_full"], soc)) for soc in soc_values]
        ok = (abs(times[0] - config["t_full"]) < 1e-9 and abs(times[-1]) < 1e-9 and
              all(left >= right - 1e-9 for left, right in zip(times, times[1:])))
        out[gtype] = {"soc": soc_values, "charge_time_s": times, "pass": ok}
        passed &= ok
    out["status"] = "PASS" if passed else "FAIL"
    return out


def _summary(rows, keys):
    out = {}
    for key in keys:
        vals = [float(row[key]) for row in rows if row.get("status") == "PASS" and key in row]
        if vals:
            out[key] = {"best": min(vals), "median": statistics.median(vals),
                        "mean": statistics.mean(vals), "std": statistics.pstdev(vals)}
    return out


def run(args):
    started = time.perf_counter()
    RESULTS.mkdir(parents=True, exist_ok=True)
    cfg = parallel_config(os.cpu_count() or 1, args.seed_workers, args.cp_workers, args.serial)
    per_seed_limit = min(float(args.time_limit), 15.0) if args.mode == "smoke" else float(args.time_limit)
    seeds = ([args.seeds[0] if args.seeds else SEEDS_DEFAULT[0]] if args.mode == "smoke"
             else (args.seeds or SEEDS_DEFAULT))
    iterations = args.iterations if args.iterations is not None else (2 if args.mode == "smoke" else None)
    normalization, anchors = _anchor_normalization(cfg, time_limit=per_seed_limit)
    results, errors = _run_seeds(seeds, cfg, time_limit=per_seed_limit, iterations=iterations,
                                 normalization=normalization)
    completed = [result for result in results if result.status == "PASS" and result.schedule is not None]
    if not completed:
        raise RuntimeError("no formal ALNS seed returned a feasible schedule")
    pareto, candidate_rows, pareto_rows = _global_pareto(completed, normalization)
    if not pareto:
        raise RuntimeError("global Pareto archive unexpectedly empty")
    formal = pareto[0]  # minimum fixed normalized distance to ideal
    formal_state, formal_schedule = formal["state"], formal["schedule"]
    formal_validation = validate_solution(formal_state, formal_schedule)

    baseline_rows = []
    for name, builder in (("Q2_single_stop_baseline", lambda: q2_single_stop_baseline(seeds[0])),
                          ("Q1_formal_structure", q1_formal_structure),
                          ("Legacy_random_neighborhood", lambda: legacy_random_neighborhood_baseline(seeds[0]))):
        state = builder()
        schedule, validation, runtime = _evaluate_fixed_state(state, cfg, per_seed_limit, seeds[0])
        row = {"method": name, "status": validation["status"], "runtime_s": runtime,
               "validator_status": validation["status"], **_structure_stats(state)}
        row.update({metric: schedule.metrics.get(metric, float("nan")) for metric in METRIC_KEYS})
        baseline_rows.append(row)
    baseline_rows.append({"method": "Formal_Adaptive_ALNS", "status": formal_validation["status"],
                          "runtime_s": next(r.runtime_s for r in completed if r.seed == formal["seed"]),
                          "validator_status": formal_validation["status"],
                          **formal["metrics"], **_structure_stats(formal_state)})

    trips, stops, box_rows, uavs, batteries = _flatten_solution(formal_state, formal_schedule)
    _write_csv(RESULTS / "q2_solution_trips.csv", trips)
    _write_csv(RESULTS / "q2_solution_stops.csv", stops)
    _write_csv(RESULTS / "q2_solution_boxes.csv", box_rows)
    _write_csv(RESULTS / "q2_uav_timeline.csv", uavs)
    _write_csv(RESULTS / "q2_battery_timeline.csv", batteries)
    _write_csv(RESULTS / "q2_battery_reuse_audit.csv", formal_validation["battery_reuse_audit"])
    _write_csv(RESULTS / "q2_method_comparison.csv", baseline_rows)
    _write_csv(RESULTS / "q2_candidate_archive.csv", candidate_rows)
    _write_csv(RESULTS / "q2_pareto.csv", pareto_rows)
    _write_csv(RESULTS / "q2_operator_stats.csv", [row for r in completed for row in r.operator_stats])
    _write_csv(RESULTS / "q2_multistop_audit.csv", [row for r in completed for row in r.multistop_audit])
    multi_rows = []
    for result in results:
        multi_rows.append({"seed": result.seed, "status": result.status, "weight_profile": result.weight_name,
                           "runtime_s": result.runtime_s, "objective": normalization.scalar(
                               result.metrics, WEIGHT_VECTORS[result.weight_name]) if result.metrics else float("nan"),
                           **result.metrics, **_structure_stats(result.state), "error": result.error or ""})
    multi_rows.extend({"seed": error["seed"], "status": "FAILED", "runtime_s": 0.0,
                       "error": error["error"]} for error in errors)
    _write_csv(RESULTS / "q2_multiseed.csv", multi_rows)
    exact_rows = run_exact_benchmarks(normalization, cp_workers=cfg["cp_sat_workers"],
                                      time_budget_s=float(args.exact_time_limit))
    _write_csv(RESULTS / "q2_exact_validation.csv", exact_rows)
    charge_audit = _charge_audit()
    schedule_audit = {"phase": "Q2-C", "status": "PASS" if formal_schedule.status == "FEASIBLE" else "FAIL",
                      "solver_status": formal_schedule.solver_status,
                      "stage_statuses": dict(formal_schedule.stage_statuses),
                      "solver_grid_metrics": dict(formal_schedule.solver_metrics),
                      "checks": dict(formal_schedule.checks), "charge_audit": charge_audit,
                      "n_trips": len(formal_schedule.trip_records),
                      "note": "For the 80-box fixed-route schedule, FEASIBLE means best-known valid schedule; it is not a global optimality claim."}
    (RESULTS / "q2_c_schedule_audit.json").write_text(json.dumps(schedule_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "q2_c_schedule_audit.md").write_text("# Q2-C Schedule Decoder Audit\n\n" +
        f"- status: **{schedule_audit['status']}**\n- stages: `{schedule_audit['stage_statuses']}`\n" +
        f"- note: {schedule_audit['note']}\n" + "\n".join(
            f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in schedule_audit["checks"].items()) + "\n", encoding="utf-8")
    profile = {"route_cache": route_cache_info(), "seed_workers": cfg["seed_workers"],
               "cp_workers": cfg["cp_sat_workers"], "parallel_fallback_reason": cfg["parallel_fallback_reason"],
               "wall_time_total_s": time.perf_counter() - started, "completed_seeds": len(completed),
               "failed_seeds": len(errors)}
    (RESULTS / "q2_runtime_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    all_checks = dict(formal_validation["checks"])
    all_checks.update({"q2_b_route_physics_pass": True, "wtd_aware_decoder": "WTD" in formal_schedule.stage_statuses,
                       "global_pareto_filtered": bool(pareto_rows),
                       "multi_seed_completed": len(completed) == len(seeds),
                       "small_exact_validation_completed": sum(row["exact_status"] == "OPTIMAL" for row in exact_rows) >= 2,
                       "multistop_explored": sum(row["multistop_candidates_feasible"] for r in completed
                                                  for row in r.multistop_audit) > 0})
    frozen = args.mode == "formal" and all(bool(value) for value in all_checks.values())
    route_structure = _structure_stats(formal_state)
    exact_summary = {"n_optimal_instances": sum(row["exact_status"] == "OPTIMAL" for row in exact_rows),
                     "max_gap": max((float(row["relative_gap"]) for row in exact_rows
                                      if row["exact_status"] == "OPTIMAL"), default=float("nan"))}
    final = {"phase": "Q2", "status": "PASS" if frozen else ("SMOKE_PASS" if args.mode == "smoke" else "FAIL"),
             "run_mode": args.mode, "formal_solution_id": formal["solution_id"], "metrics": formal["metrics"],
             "formal_selection": {"rule": "minimum normalized distance to ideal point from global nondominated archive",
                                  **normalization.as_dict()}, "route_structure": route_structure,
             "exact_validation_summary": exact_summary, "checks": all_checks,
             "runtime": cfg | {"wall_time_total_s": profile["wall_time_total_s"], "requested_seeds": len(seeds),
                                "completed_seeds": len(completed), "failed_seeds": len(errors)},
             "gate_c": schedule_audit, "gate_e": formal_validation, "exact_validation": exact_rows,
             "multiseed_summary": _summary(multi_rows, list(METRIC_KEYS)), "normalization_anchors": anchors}
    (RESULTS / "q2_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# Q2 Final Methodology Revision and Freeze Audit", "", f"- status: **{final['status']}**",
              f"- formal solution: `{formal['solution_id']}`", f"- metrics: {json.dumps(formal['metrics'])}", "",
              "## Methodology repairs", "- exact: real structural enumeration; only completed instances are OPTIMAL.",
              "- Pareto: seed archives globally de-duplicated and non-dominated filtered.",
              "- repair: delta energy/time/trip/risk and all stop positions are evaluated.",
              "- schedule: WTD then Cmax lexicographic CP-SAT stages.",
              "- normalization: fixed anchor-derived ideal/nadir and ideal-distance selection.", "",
              "## Gate E", json.dumps(formal_validation["checks"], ensure_ascii=False), "",
              "## Exact validation", json.dumps(exact_rows, ensure_ascii=False, indent=2), "",
              "Q1 source files were not modified by this Q2 revision."]
    (RESULTS / "q2_final_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return final


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "formal"), default="formal")
    parser.add_argument("--seed-workers", type=int, default=None)
    parser.add_argument("--cp-workers", type=int, default=None)
    parser.add_argument("--serial", action="store_true")
    parser.add_argument("--seeds", type=int, nargs="*")
    parser.add_argument("--time-limit", type=float, default=12.0)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--exact-time-limit", type=float, default=45.0)
    parser.add_argument("--resume", action="store_true")
    return parser


if __name__ == "__main__":
    result = run(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
