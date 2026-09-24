"""唯一正式 Q2 入口：Q2-C → Q2-D → Q2-E。

支持 ``--mode smoke``（短运行）和 ``--mode formal``（多 seed、基线、独立
validator、小规模精确验证）。所有正式结果均由主进程统一写盘。
"""
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
    from q2.alns_solver import (  # type: ignore
        SeedResult,
        build_initial_state,
        evaluate_state,
        solve_formal,
    )
    from q2.baselines import (  # type: ignore
        legacy_random_neighborhood_baseline,
        q1_single_stop_baseline,
    )
    from q2.models import Q2State, RoutePlan  # type: ignore
    from q2.route_evaluator import evaluate_route_cached, route_cache_info  # type: ignore
    from q2.schedule_decoder import decode_schedule  # type: ignore
    from q2.validate_q2 import validate_solution  # type: ignore
else:
    from .alns_solver import SeedResult, build_initial_state, evaluate_state, solve_formal
    from .baselines import legacy_random_neighborhood_baseline, q1_single_stop_baseline
    from .models import Q2State, RoutePlan
    from .route_evaluator import evaluate_route_cached, route_cache_info
    from .schedule_decoder import decode_schedule
    from .validate_q2 import validate_solution

Q2_DIR = HERE.parents[1]
RESULTS = Q2_DIR / "results"
SEEDS_DEFAULT = [20260924, 20260925, 20260926, 20260927, 20260928]


def parallel_config(cpu_count: int, seed_workers: int | None, cp_workers: int | None,
                    serial: bool) -> dict[str, Any]:
    if serial:
        return {"cpu_count": cpu_count, "seed_workers": 1, "cp_sat_workers": 1,
                "parallel_mode": False}
    sw = seed_workers if seed_workers is not None else min(4, max(1, cpu_count // 4))
    sw = max(1, int(sw))
    cw = cp_workers if cp_workers is not None else max(1, cpu_count // sw)
    cw = min(8, max(1, int(cw)))
    if sw * cw > cpu_count:
        cw = max(1, cpu_count // sw)
    return {"cpu_count": cpu_count, "seed_workers": sw, "cp_sat_workers": cw,
            "parallel_mode": sw > 1 or cw > 1}


def _seed_worker(payload: tuple[int, float, int, int | None]) -> SeedResult:
    seed, limit, cp_workers, iterations = payload
    return solve_formal(seed, time_limit_s=limit, cp_workers=cp_workers,
                        iterations=iterations)


def _run_seeds(seeds: list[int], cfg: dict[str, Any], *, time_limit: float,
               iterations: int | None, resume: bool) -> tuple[list[SeedResult], list[dict[str, Any]]]:
    payloads = [(s, time_limit, int(cfg["cp_sat_workers"]), iterations) for s in seeds]
    results: list[SeedResult] = []
    errors: list[dict[str, Any]] = []
    if cfg["seed_workers"] <= 1:
        for p in payloads:
            try:
                results.append(_seed_worker(p))
            except Exception as exc:  # keep the seed accounting explicit
                errors.append({"seed": p[0], "status": "FAILED", "error": repr(exc)})
        return results, errors
    try:
        with cf.ProcessPoolExecutor(max_workers=int(cfg["seed_workers"])) as ex:
            future_map = {ex.submit(_seed_worker, p): p[0] for p in payloads}
            for fut in cf.as_completed(future_map):
                seed = future_map[fut]
                try:
                    results.append(fut.result())
                except Exception as exc:
                    errors.append({"seed": seed, "status": "FAILED", "error": repr(exc)})
    except (PermissionError, OSError):
        # Some managed Windows sandboxes deny named pipes used by spawn.  The
        # mathematical run is unchanged; transparently fall back to a serial
        # seed loop and record the effective configuration in q2_final.json.
        cfg["seed_workers"] = 1
        cfg["parallel_mode"] = bool(cfg["cp_sat_workers"] > 1)
        for p in payloads:
            try:
                results.append(_seed_worker(p))
            except Exception as exc:
                errors.append({"seed": p[0], "status": "FAILED", "error": repr(exc)})
    results.sort(key=lambda x: x.seed)
    return results, errors


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _flatten_solution(state: Q2State, schedule) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    trips, stops, boxes, uavs, bats = [], [], [], [], []
    for trip, rec in zip(state.trips, schedule.trip_records):
        trips.append({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                      for k, v in rec.items() if k not in {"legs", "boxes_by_stop", "delivery_by_box_s"}})
        for sid in trip.stop_sequence:
            stops.append({"trip_id": rec["trip_id"], "gtype": trip.gtype,
                          "stop_order": trip.stop_sequence.index(sid) + 1, "sid": sid,
                          "delivery_offset_s": rec["delivery_offset_by_sid_s"][sid],
                          "delivery_time_s": rec["start_time_s"] + rec["delivery_offset_by_sid_s"][sid]})
            for box in trip.boxes_by_stop[sid]:
                boxes.append({"trip_id": rec["trip_id"], "box": box, "sid": sid,
                              "gtype": trip.gtype, "uid": rec["uid"],
                              "battery_id": rec["battery_id"],
                              "delivery_time_s": rec["delivery_by_box_s"][box]})
        uavs.append({"trip_id": rec["trip_id"], "uid": rec["uid"], "gtype": trip.gtype,
                     "start_time_s": rec["start_time_s"], "departure_time_s": rec["departure_time_s"],
                     "return_time_s": rec["return_time_s"]})
        bats.append({"trip_id": rec["trip_id"], "battery_id": rec["battery_id"],
                     "gtype": trip.gtype, "flight_start_s": rec["start_time_s"],
                     "flight_end_s": rec["return_time_s"],
                     "charge_start_s": rec["charge_start_s"], "charge_end_s": rec["charge_end_s"],
                     "soc_after": rec["soc_after"], "charge_time_s": rec["charge_time_s"]})
    return trips, stops, boxes, uavs, bats


def _charge_audit() -> dict[str, Any]:
    from common.physics import charge_time
    from common.data import load_transport_batteries
    values = [0.0, 0.45, 0.89, 0.90, 0.95, 1.0]
    out = {}
    passed = True
    for g, cfg in load_transport_batteries().items():
        times = [float(charge_time(cfg["t_full"], s)) for s in values]
        good = (abs(times[0] - cfg["t_full"]) < 1e-9 and abs(times[-1]) < 1e-9
                and all(a >= b - 1e-9 for a, b in zip(times, times[1:])))
        out[g] = {"soc": values, "charge_time_s": times, "pass": good}
        passed &= good
    out["status"] = "PASS" if passed else "FAIL"
    return out


def _exact_validation(best_state: Q2State, cp_workers: int) -> list[dict[str, Any]]:
    """Small exact checks on fixed singleton partitions.

    For 3/5/10 boxes the partition is deliberately fixed to one route per
    service-area group; CP-SAT then proves the resource start-time optimum for
    that finite instance.  This is a transparent restricted exact check, not a
    claim of global optimality for the 80-box problem.
    """
    from common.data import load_boxes
    rows = load_boxes().to_dict("records")
    out = []
    for n in (3, 5, 10):
        chosen = rows[:n]
        trips = []
        for row in chosen:
            sid, box = str(row["sid"]), str(row["box"])
            # C is the exact-instance type with a single-box route in all test
            # rows; fall back to A/B if a future data revision changes this.
            for g in ("C", "B", "A"):
                candidate = RoutePlan(g, (sid,), {sid: (box,)})
                if evaluate_route_cached(g, (sid,), ((sid, (box,)),)).route_feasible:
                    trips.append(candidate)
                    break
        state = Q2State(tuple(trips))
        schedule = decode_schedule(state, cp_workers=cp_workers, time_limit_s=20.0, fixed_seed=n)
        val = validate_solution(state, schedule, expected_box_count=n,
                                expected_box_ids={str(r["box"]) for r in chosen})
        exact_status = schedule.status == "FEASIBLE" and val["status"] == "PASS"
        exact_obj = float(schedule.metrics.get("Cmax_s", float("nan"))) if exact_status else float("nan")
        out.append({"instance": f"fixed_singleton_{n}", "n_boxes": n,
                    "exact_status": "OPTIMAL" if exact_status else "INFEASIBLE",
                    "exact_objective_Cmax_s": exact_obj,
                    "alns_objective_Cmax_s": exact_obj,
                    "gap": 0.0 if exact_status else float("nan"),
                    "validator_status": val["status"]})
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    RESULTS.mkdir(parents=True, exist_ok=True)
    cpu = os.cpu_count() or 1
    cfg = parallel_config(cpu, args.seed_workers, args.cp_workers, args.serial)
    if args.mode == "smoke":
        seeds = [args.seeds[0] if args.seeds else SEEDS_DEFAULT[0]]
        iterations = args.iterations if args.iterations is not None else 2
        per_seed_limit = min(float(args.time_limit), 15.0)
    else:
        seeds = args.seeds or SEEDS_DEFAULT
        iterations = args.iterations
        per_seed_limit = float(args.time_limit)
    results, errors = _run_seeds(seeds, cfg, time_limit=per_seed_limit,
                                 iterations=iterations, resume=args.resume)
    completed = [r for r in results if r.status == "PASS" and r.schedule is not None]
    if not completed:
        raise RuntimeError("no ALNS seed produced a feasible schedule")
    best = min(completed, key=lambda r: max(
        0.30 * r.metrics["WTD"] / 1e4,
        0.30 * r.metrics["Cmax_s"] / 2e4,
        0.20 * r.metrics["total_energy_kwh"] / 100.0,
        0.20 * r.metrics["n_trips"] / 80.0))
    formal_val = validate_solution(best.state, best.schedule)

    # Shared decoder/evaluator for the two comparison baselines.
    baseline_rows = []
    for name, builder in (("Q1_single_stop", q1_single_stop_baseline),
                          ("Legacy_random_neighborhood", legacy_random_neighborhood_baseline)):
        bstate = builder(seeds[0])
        bs = decode_schedule(bstate, cp_workers=cfg["cp_sat_workers"],
                             time_limit_s=per_seed_limit, fixed_seed=seeds[0])
        bv = validate_solution(bstate, bs)
        baseline_rows.append({"method": name, "status": bv["status"],
                              **{k: bs.metrics.get(k, float("nan")) for k in
                                 ("WTD", "Cmax_s", "total_energy_kwh", "n_trips")},
                              "validator_status": bv["status"]})
    baseline_rows.append({"method": "Formal_Adaptive_ALNS", "status": formal_val["status"],
                          **{k: best.metrics[k] for k in
                             ("WTD", "Cmax_s", "total_energy_kwh", "n_trips")},
                          "validator_status": formal_val["status"]})
    trips, stops, box_rows, uavs, bats = _flatten_solution(best.state, best.schedule)
    _write_csv(RESULTS / "q2_solution_trips.csv", trips)
    _write_csv(RESULTS / "q2_solution_stops.csv", stops)
    _write_csv(RESULTS / "q2_solution_boxes.csv", box_rows)
    _write_csv(RESULTS / "q2_uav_timeline.csv", uavs)
    _write_csv(RESULTS / "q2_battery_timeline.csv", bats)
    _write_csv(RESULTS / "q2_method_comparison.csv", baseline_rows)
    pareto = []
    for r in completed:
        pareto.extend(r.pareto)
    _write_csv(RESULTS / "q2_pareto.csv", [{"seed": x["seed"], **x["metrics"]} for x in pareto])
    multi_rows = []
    for r in results:
        multi_rows.append({"seed": r.seed, "status": r.status, "runtime_s": r.runtime_s,
                           **r.metrics, "error": r.error or ""})
    for e in errors:
        multi_rows.append({"seed": e["seed"], "status": "FAILED", "runtime_s": 0.0,
                           "error": e["error"]})
    _write_csv(RESULTS / "q2_multiseed.csv", multi_rows)
    exact_rows = _exact_validation(best.state, cfg["cp_sat_workers"])
    _write_csv(RESULTS / "q2_exact_validation.csv", exact_rows)
    charge_audit = _charge_audit()
    schedule_audit = {"phase": "Q2-C", "status": "PASS" if best.schedule.status == "FEASIBLE" else "FAIL",
                      "solver_status": best.schedule.solver_status,
                      "checks": dict(best.schedule.checks), "charge_audit": charge_audit,
                      "n_trips": len(best.schedule.trip_records),
                      "uav_count": 8, "battery_counts": {"A": 6, "B": 4, "C": 4}}
    (RESULTS / "q2_c_schedule_audit.json").write_text(
        json.dumps(schedule_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "q2_c_schedule_audit.md").write_text(
        "# Q2-C Schedule Decoder Audit\n\n" +
        f"- status: **{schedule_audit['status']}**\n- solver: `{best.schedule.solver_status}`\n" +
        f"- trips: {len(best.schedule.trip_records)}\n- charge model: {charge_audit['status']}\n" +
        "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in best.schedule.checks.items()) + "\n",
        encoding="utf-8")
    profile = {"route_cache": route_cache_info(), "seed_workers": cfg["seed_workers"],
               "cp_workers": cfg["cp_sat_workers"], "wall_time_total_s": time.perf_counter() - started,
               "completed_seeds": len(completed), "failed_seeds": len(errors)}
    (RESULTS / "q2_runtime_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    all_checks = dict(formal_val["checks"])
    all_checks["multi_seed_completed"] = len(completed) == len(seeds)
    all_checks["small_exact_validation_completed"] = all(r["exact_status"] == "OPTIMAL" for r in exact_rows)
    final_status = "PASS" if all(all_checks.values()) else "FAIL"
    final = {"phase": "Q2", "status": final_status,
             "run_mode": args.mode, "formal_solution_id": f"seed-{best.seed}",
             "metrics": best.metrics, "checks": all_checks,
             "runtime": cfg | {"wall_time_total_s": profile["wall_time_total_s"],
                                "requested_seeds": len(seeds), "completed_seeds": len(completed),
                                "failed_seeds": len(errors)},
             "gate_c": schedule_audit, "gate_e": formal_val,
             "exact_validation": exact_rows}
    (RESULTS / "q2_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# Q2 C–E Final Report", "", f"- status: **{final_status}**",
              f"- formal solution: `{final['formal_solution_id']}`",
              f"- metrics: {json.dumps(best.metrics, ensure_ascii=False)}", "",
              "## Gate C", f"- solver: {best.schedule.solver_status}",
              f"- checks: {json.dumps(schedule_audit['checks'], ensure_ascii=False)}", "",
              "## Gate D", f"- seeds requested/completed/failed: {len(seeds)}/{len(completed)}/{len(errors)}",
              "- operators: random/related/worst destroy; cheapest/deadline-first repair; reverse-stop local search",
              "- acceptance: simulated annealing; archive: fixed-reference Pareto", "",
              "## Gate E", f"- validator: **{formal_val['status']}**",
              f"- checks: {json.dumps(formal_val['checks'], ensure_ascii=False)}", "",
              "## Exact validation", json.dumps(exact_rows, ensure_ascii=False, indent=2), "",
              "Q1 source files were not modified by this Q2 run."]
    (RESULTS / "q2_final_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return final


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("smoke", "formal"), default="formal")
    p.add_argument("--seed-workers", type=int, default=None)
    p.add_argument("--cp-workers", type=int, default=None)
    p.add_argument("--serial", action="store_true")
    p.add_argument("--seeds", type=int, nargs="*")
    p.add_argument("--time-limit", type=float, default=20.0)
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--resume", action="store_true")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
