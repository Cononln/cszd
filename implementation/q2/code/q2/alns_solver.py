"""Q2-D formal adaptive ALNS.

The implementation deliberately keeps resource variables out of the ALNS
state.  A candidate is always evaluated through the single chain
``Q2-B route evaluator -> Q2-C decoder``.  This makes the method usable with
either the CP-SAT decoder or its documented minimal-environment fallback.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .deadlines import hard_deadline
from .models import Q2State, RoutePlan
from .normalization import METRIC_KEYS, Normalization
from .route_evaluator import evaluate_route_cached, route_cache_info
from .schedule_decoder import decode_schedule


G_TYPES = ("A", "B", "C")
WEIGHT_VECTORS = {
    "balanced": {"WTD": .25, "Cmax_s": .25, "total_energy_kwh": .25, "n_trips": .25},
    "time-focused": {"WTD": .40, "Cmax_s": .30, "total_energy_kwh": .15, "n_trips": .15},
    "energy-focused": {"WTD": .20, "Cmax_s": .20, "total_energy_kwh": .40, "n_trips": .20},
    "trip-focused": {"WTD": .20, "Cmax_s": .20, "total_energy_kwh": .20, "n_trips": .40},
}


@dataclass
class SeedResult:
    seed: int
    status: str
    state: Q2State
    schedule: Any = None
    metrics: dict[str, float] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    pareto: list[dict[str, Any]] = field(default_factory=list)
    runtime_s: float = 0.0
    error: str | None = None
    weight_name: str = "balanced"
    operator_stats: list[dict[str, Any]] = field(default_factory=list)
    multistop_audit: list[dict[str, Any]] = field(default_factory=list)


def _box_table():
    # Imported lazily so multiprocessing workers initialize the read-only data
    # independently on Windows (open raster handles are never shared).
    from common.data import load_boxes
    return {str(r["box"]): r for r in load_boxes().to_dict("records")}


def _route_key(trip):
    return (trip.gtype, tuple(trip.stop_sequence),
            tuple((sid, tuple(trip.boxes_by_stop[sid])) for sid in trip.stop_sequence))


def _route_eval(trip):
    return evaluate_route_cached(*_route_key(trip))


def _pack_route(gtype: str, sid: str, boxes: list[str]):
    if not boxes:
        return None
    trip = RoutePlan(gtype=gtype, stop_sequence=(sid,), boxes_by_stop={sid: tuple(boxes)})
    return trip if _route_eval(trip).route_feasible else None


def build_initial_state(seed: int = 20260924) -> Q2State:
    """Build a feasible bin-packing seed without a hard stop-count cap.

    Boxes are inserted deadline-first.  Existing bins are filled before a new
    bin is opened; A/B are preferred for parallel fleet capacity and C is used
    when its larger payload/volume is needed.
    """
    from common.data import load_boxes
    boxes = load_boxes().to_dict("records")
    rng = np.random.default_rng(seed)
    by_sid: dict[str, list[dict]] = {}
    for row in boxes:
        by_sid.setdefault(str(row["sid"]), []).append(row)
    trips: list[RoutePlan] = []
    for sid, rows in sorted(by_sid.items()):
        rows.sort(key=lambda r: (float(hard_deadline(r) or 1e12), -float(r["mass"]),
                                 str(r["box"])))
        # A slight seed-dependent tie permutation supplies independent ALNS
        # starts while preserving deadline-first ordering.
        if len(rows) > 2:
            tied = rows[:]
            rng.shuffle(tied)
            rows.sort(key=lambda r: (float(hard_deadline(r) or 1e12),
                                     str(r["box"]) if hard_deadline(r) is not None else ""))
        bins: list[RoutePlan] = []
        for row in rows:
            box = str(row["box"])
            is_hard = hard_deadline(row) is not None
            candidates: list[tuple[tuple[float, ...], RoutePlan]] = []
            for i, old in enumerate(bins):
                pack = list(old.boxes_by_stop[sid]) + [box]
                ev = _pack_route(old.gtype, sid, pack)
                if ev is not None:
                    # Keep urgent and soft boxes separable when possible.  This
                    # preserves the early-deadline parallelism needed by the
                    # real fleet while still filling same-class bins.
                    old_has_hard = any(hard_deadline(table_row) is not None
                                       for table_row in (_box_table()[b]
                                                         for b in old.box_ids))
                    separation = 0.0 if is_hard == old_has_hard else 2.0
                    e = _route_eval(ev)
                    candidates.append(((separation, -len(pack), float(e.route_duration_s)), ev))
            for g in G_TYPES:
                ev = _pack_route(g, sid, [box])
                if ev is not None:
                    e = _route_eval(ev)
                    # Urgent cargo uses the larger parallel A/B fleet first;
                    # soft cargo uses C first to reduce the number of trips.
                    gp = ({"A": 0.0, "B": 1.0, "C": 2.0} if is_hard
                          else {"C": 0.0, "B": 1.0, "A": 2.0})[g]
                    candidates.append(((1.0, gp, float(e.route_duration_s)), ev))
            if not candidates:
                raise ValueError(f"box {box} cannot be placed on any transport type")
            # Existing bins beat opening a new one, and fuller bins beat sparse
            # bins.  A stable tie-break keeps output reproducible.
            candidates.sort(key=lambda x: x[0])
            chosen = candidates[0][1]
            replaced = False
            for i, old in enumerate(bins):
                if old.gtype == chosen.gtype and old.stop_sequence == chosen.stop_sequence:
                    if set(old.box_ids).issubset(set(chosen.box_ids)):
                        bins[i] = chosen
                        replaced = True
                        break
            if not replaced:
                bins.append(chosen)
        trips.extend(bins)
    return Q2State(tuple(trips))


def objective(metrics: dict[str, float], normalization: Normalization | None = None,
              weights: dict[str, float] | None = None) -> float:
    """Fixed-reference normalized weighted Tchebycheff scalarization."""
    if normalization is None:
        # Compatibility fallback; formal runs always pass anchor-derived bounds.
        normalization = Normalization.from_metrics([{
            "WTD": 0.0, "Cmax_s": 0.0, "total_energy_kwh": 0.0, "n_trips": 0.0},
            {"WTD": 1.0, "Cmax_s": 1.0, "total_energy_kwh": 1.0, "n_trips": 1.0},
        ])
    return normalization.scalar(metrics, weights or WEIGHT_VECTORS["balanced"])


def dominates(a: dict[str, float], b: dict[str, float]) -> bool:
    keys = METRIC_KEYS
    return all(float(a[k]) <= float(b[k]) + 1e-9 for k in keys) and \
        any(float(a[k]) < float(b[k]) - 1e-9 for k in keys)


def update_archive(archive: list[dict[str, Any]], item: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = item["metrics"]
    if any(dominates(x["metrics"], metrics) or x["metrics"] == metrics for x in archive):
        return archive
    out = [x for x in archive if not dominates(metrics, x["metrics"])]
    out.append(item)
    return out


def evaluate_state(state: Q2State, *, cp_workers: int = 1,
                   decoder_time_limit_s: float = 5.0, seed: int = 0):
    if state.unassigned:
        return None
    try:
        schedule = decode_schedule(state, cp_workers=cp_workers,
                                   time_limit_s=decoder_time_limit_s,
                                   fixed_seed=seed)
    except (ValueError, KeyError, RuntimeError) as exc:
        return None
    if schedule.status != "FEASIBLE":
        return None
    checks = schedule.checks
    if not all(bool(v) for v in checks.values()):
        return None
    return schedule


def _destroy_random(state: Q2State, fraction: float, rng: np.random.Generator) -> Q2State:
    boxes = list(state.box_ids)
    if not boxes:
        return state
    n_remove = max(1, int(round(len(boxes) * fraction)))
    removed = set(rng.choice(boxes, size=min(n_remove, len(boxes)), replace=False).tolist())
    trips = []
    for trip in state.trips:
        grouped = {sid: tuple(b for b in trip.boxes_by_stop[sid] if b not in removed)
                   for sid in trip.stop_sequence}
        grouped = {s: b for s, b in grouped.items() if b}
        if grouped:
            trips.append(RoutePlan(trip.gtype, tuple(grouped), grouped))
    return Q2State(tuple(trips), tuple(sorted(removed)))


def _destroy_related(state: Q2State, fraction: float, rng: np.random.Generator) -> Q2State:
    boxes = list(state.box_ids)
    if not boxes:
        return state
    seed_box = str(rng.choice(boxes))
    sid = seed_box.split("-")[0]
    related = [b for b in boxes if b.startswith(sid + "-")]
    n_remove = max(1, int(round(len(boxes) * fraction)))
    rng.shuffle(related)
    return _remove_ids(state, set(related[:n_remove]))


def _remove_ids(state: Q2State, removed: set[str]) -> Q2State:
    trips = []
    for trip in state.trips:
        grouped = {sid: tuple(b for b in trip.boxes_by_stop[sid] if b not in removed)
                   for sid in trip.stop_sequence}
        grouped = {s: b for s, b in grouped.items() if b}
        if grouped:
            trips.append(RoutePlan(trip.gtype, tuple(grouped), grouped))
    return Q2State(tuple(trips), tuple(sorted(set(state.unassigned) | removed)))


def _destroy_high_energy(state: Q2State, fraction: float, rng: np.random.Generator) -> Q2State:
    scored = []
    for trip in state.trips:
        ev = _route_eval(trip)
        scored.append((float(ev.total_route_energy_kwh) + 0.01 * float(ev.route_duration_s), trip))
    scored.sort(reverse=True, key=lambda x: x[0])
    n = max(1, int(round(len(state.box_ids) * fraction)))
    removed = set()
    for _, trip in scored:
        removed.update(trip.box_ids)
        if len(removed) >= n:
            break
    return _remove_ids(state, removed)


_destroy_worst = _destroy_high_energy  # backwards-compatible operator alias


def _destroy_high_wtd(state: Q2State, schedule, fraction: float,
                      rng: np.random.Generator) -> Q2State:
    contribution = {str(r["trip_id"]): float(r["wtd_contribution"])
                    for r in schedule.trip_records}
    ranked = sorted(enumerate(state.trips),
                    key=lambda x: contribution.get(f"T{x[0] + 1:03d}", 0.0), reverse=True)
    n = max(1, int(round(len(state.box_ids) * fraction)))
    removed: set[str] = set()
    for _, trip in ranked:
        removed.update(trip.box_ids)
        if len(removed) >= n:
            break
    return _remove_ids(state, removed)


def _destroy_whole_route(state: Q2State, rng: np.random.Generator) -> Q2State:
    if not state.trips:
        return state
    trip = state.trips[int(rng.integers(0, len(state.trips)))]
    return _remove_ids(state, set(trip.box_ids))


def _destroy_stop(state: Q2State, rng: np.random.Generator) -> Q2State:
    stops = [(sid, trip) for trip in state.trips for sid in trip.stop_sequence]
    if not stops:
        return state
    sid, _ = stops[int(rng.integers(0, len(stops)))]
    removed = {box for trip in state.trips if sid in trip.stop_sequence
               for box in trip.boxes_by_stop[sid]}
    return _remove_ids(state, removed)


def _deadline_risk(trip: RoutePlan, table: dict[str, dict[str, Any]]) -> float:
    """Safe lower-bound tardiness risk used only to rank insertions."""
    ev = _route_eval(trip)
    risk = 0.0
    for sid, offset in ev.delivery_offset_by_sid.items():
        for box in trip.boxes_by_stop[sid]:
            deadline = hard_deadline(table[box])
            if deadline is not None:
                risk += max(0.0, float(offset) - float(deadline)) / 60.0
    return risk


def _candidate_score(delta_e: float, delta_t: float, delta_n: int, risk: float) -> float:
    """Incremental repair ranking; final acceptance always uses the decoder."""
    return float(delta_e) + 0.002 * float(delta_t) + 6.0 * int(delta_n) + 100.0 * float(risk)


def _enumerate_insertions(trips: list[RoutePlan], box: str,
                          table: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Evaluate every stop position and use delta route cost, never absolute cost."""
    sid = str(table[box]["sid"])
    audit = {"candidate_routes_evaluated": 0, "multistop_candidates_evaluated": 0,
             "multistop_candidates_feasible": 0}
    candidates: list[dict[str, Any]] = []
    for idx, old in enumerate(trips):
        old_ev = _route_eval(old)
        orders = [tuple(old.stop_sequence)] if sid in old.stop_sequence else [
            tuple(old.stop_sequence[:pos]) + (sid,) + tuple(old.stop_sequence[pos:])
            for pos in range(len(old.stop_sequence) + 1)
        ]
        for order in orders:
            for gtype in G_TYPES:
                grouped = {s: tuple(old.boxes_by_stop[s]) for s in old.stop_sequence}
                grouped.setdefault(sid, tuple())
                grouped[sid] = grouped[sid] + (box,)
                audit["candidate_routes_evaluated"] += 1
                if len(order) > 1:
                    audit["multistop_candidates_evaluated"] += 1
                try:
                    new = RoutePlan(gtype, order, grouped)
                    ev = _route_eval(new)
                except ValueError:
                    continue
                if not ev.route_feasible:
                    continue
                if len(order) > 1:
                    audit["multistop_candidates_feasible"] += 1
                delta_e = float(ev.total_route_energy_kwh) - float(old_ev.total_route_energy_kwh)
                delta_t = float(ev.route_duration_s) - float(old_ev.route_duration_s)
                risk = _deadline_risk(new, table)
                candidates.append({"trip_index": idx, "route": new, "is_new": False,
                                   "delta_e": delta_e, "delta_t": delta_t, "delta_n": 0,
                                   "risk": risk,
                                   "base_score": _candidate_score(delta_e, delta_t, 0, risk)})
    # New trips are explicit alternatives with ΔN=1, not implicit singleton
    # preference.  No max-stop limit is imposed on existing insertions.
    for gtype in G_TYPES:
        audit["candidate_routes_evaluated"] += 1
        try:
            new = RoutePlan(gtype, (sid,), {sid: (box,)})
            ev = _route_eval(new)
        except ValueError:
            continue
        if not ev.route_feasible:
            continue
        risk = _deadline_risk(new, table)
        candidates.append({"trip_index": len(trips), "route": new, "is_new": True,
                           "delta_e": float(ev.total_route_energy_kwh),
                           "delta_t": float(ev.route_duration_s), "delta_n": 1,
                           "risk": risk,
                           "base_score": _candidate_score(float(ev.total_route_energy_kwh),
                                                          float(ev.route_duration_s), 1, risk)})
    return candidates, audit


def _choose_insertion(candidates: list[dict[str, Any]], mode: str) -> dict[str, Any] | None:
    if not candidates:
        return None
    if mode == "energy-aware":
        return min(candidates, key=lambda c: (c["delta_e"], c["delta_t"], c["delta_n"], c["risk"]))
    if mode == "new-trip":
        new_only = [c for c in candidates if c["is_new"]]
        return min(new_only or candidates, key=lambda c: (c["risk"], c["delta_e"], c["delta_t"]))
    if mode == "deadline-first":
        return min(candidates, key=lambda c: (c["risk"], c["base_score"], c["delta_n"]))
    return min(candidates, key=lambda c: (c["base_score"], c["delta_e"], c["delta_t"]))


def _repair(state: Q2State, rng: np.random.Generator, *, mode: str = "cheapest-delta",
            with_audit: bool = False):
    """Distinct ALNS repairs with all cross-service insertion positions explored."""
    table = _box_table()
    trips = list(state.trips)
    remaining = list(state.unassigned)
    audit = {"candidate_routes_evaluated": 0, "multistop_candidates_evaluated": 0,
             "multistop_candidates_feasible": 0}
    if mode == "deadline-first":
        remaining.sort(key=lambda b: (float(hard_deadline(table[b]) or table[b]["t_exp"]), b))
    elif mode != "regret-2":
        rng.shuffle(remaining)
    while remaining:
        if mode == "regret-2":
            listings = []
            for box in remaining:
                candidates, item_audit = _enumerate_insertions(trips, box, table)
                for key, value in item_audit.items():
                    audit[key] += value
                ordered = sorted(candidates, key=lambda c: c["base_score"])
                if not ordered:
                    continue
                regret = (ordered[1]["base_score"] - ordered[0]["base_score"]
                          if len(ordered) > 1 else 1e9)
                listings.append((regret, box, ordered[0]))
            if not listings:
                result = Q2State(tuple(trips), tuple(sorted(remaining)))
                return (result, audit) if with_audit else result
            _, box, chosen = max(listings, key=lambda x: (x[0], -x[2]["risk"]))
        else:
            box = remaining[0]
            candidates, item_audit = _enumerate_insertions(trips, box, table)
            for key, value in item_audit.items():
                audit[key] += value
            chosen = _choose_insertion(candidates, mode)
            if chosen is None:
                result = Q2State(tuple(trips), tuple(sorted(remaining)))
                return (result, audit) if with_audit else result
        if chosen["is_new"]:
            trips.append(chosen["route"])
        else:
            trips[int(chosen["trip_index"])] = chosen["route"]
        remaining.remove(box)
    result = Q2State(tuple(trips))
    return (result, audit) if with_audit else result


def _local_stop_search(state: Q2State, current_schedule, *, cp_workers: int,
                       seed: int, decoder_time_limit_s: float,
                       normalization: Normalization, weights: dict[str, float]) -> tuple[Q2State, Any]:
    best_state, best_schedule = state, current_schedule
    best_obj = objective(dict(best_schedule.metrics), normalization, weights)
    for i, trip in enumerate(state.trips):
        if len(trip.stop_sequence) < 2:
            continue
        base = tuple(trip.stop_sequence)
        orders = {tuple(reversed(base))}
        for a in range(len(base)):
            for b in range(a + 1, len(base)):
                swapped = list(base)
                swapped[a], swapped[b] = swapped[b], swapped[a]
                orders.add(tuple(swapped))  # swap
                orders.add(tuple(base[:a] + base[a:b + 1][::-1] + base[b + 1:]))  # 2-opt
                moved = list(base)
                moved.insert(b, moved.pop(a))
                orders.add(tuple(moved))  # relocate
        for candidate_order in orders:
            grouped = {s: trip.boxes_by_stop[s] for s in candidate_order}
            candidate_trip = RoutePlan(trip.gtype, candidate_order, grouped)
            trips = list(state.trips)
            trips[i] = candidate_trip
            candidate_state = Q2State(tuple(trips))
            schedule = evaluate_state(candidate_state, cp_workers=cp_workers,
                                      decoder_time_limit_s=decoder_time_limit_s, seed=seed)
            if schedule is not None and objective(dict(schedule.metrics), normalization, weights) < best_obj - 1e-10:
                best_state, best_schedule = candidate_state, schedule
                best_obj = objective(dict(schedule.metrics), normalization, weights)
    return best_state, best_schedule


def _route_structure_metrics(state: Q2State) -> dict[str, float]:
    sizes = [len(trip.stop_sequence) for trip in state.trips]
    multi = [size for size in sizes if size > 1]
    return {"n_multistop_trips": float(len(multi)),
            "max_stops_per_trip": float(max(sizes, default=0)),
            "mean_stops_per_trip": float(sum(sizes) / len(sizes) if sizes else 0.0)}


def solve_formal(seed: int = 20260924, *, time_limit_s: float = 30.0,
                 iterations: int | None = None, cp_workers: int = 1,
                 normalization: Normalization | None = None,
                 weight_name: str = "balanced") -> SeedResult:
    started = time.perf_counter()
    rng = np.random.default_rng(seed)
    weights = dict(WEIGHT_VECTORS[weight_name])
    state = build_initial_state(seed)
    decoder_limit = min(5.0, max(0.5, time_limit_s / 8.0))
    current_schedule = evaluate_state(state, cp_workers=cp_workers,
                                      decoder_time_limit_s=decoder_limit, seed=seed)
    if current_schedule is None:
        return SeedResult(seed, "INFEASIBLE", state, runtime_s=time.perf_counter() - started,
                          error="initial state could not be decoded", weight_name=weight_name)
    if normalization is None:
        normalization = Normalization.from_metrics([dict(current_schedule.metrics)])
    best_state, best_schedule = state, current_schedule
    archive = update_archive([], {"seed": seed, "metrics": dict(current_schedule.metrics),
                                 "state": state, "schedule": current_schedule,
                                 "iteration": -1, "solution_id": f"seed-{seed}-init"})
    hist = []
    n_iter = iterations if iterations is not None else (max(20, min(80, int(time_limit_s * 2))))
    destroy_names = ("random", "related", "high-wtd", "high-energy", "whole-route", "stop-removal")
    repair_names = ("cheapest-delta", "regret-2", "deadline-first", "energy-aware", "new-trip")
    dw = np.ones(len(destroy_names), dtype=float)
    rw = np.ones(len(repair_names), dtype=float)
    stats = {(kind, name): {"times_used": 0, "times_accepted": 0,
                             "times_improved": 0, "times_global_best": 0,
                             "final_weight": 1.0}
             for kind, names in (("destroy", destroy_names), ("repair", repair_names))
             for name in names}
    multistop_audit: list[dict[str, Any]] = []
    temperature = 1.0
    cur_obj = objective(dict(current_schedule.metrics), normalization, weights)
    for it in range(n_iter):
        if time.perf_counter() - started >= time_limit_s:
            break
        di = int(rng.choice(len(destroy_names), p=dw / dw.sum()))
        ri = int(rng.choice(len(repair_names), p=rw / rw.sum()))
        destroy_name, repair_name = destroy_names[di], repair_names[ri]
        stats[("destroy", destroy_name)]["times_used"] += 1
        stats[("repair", repair_name)]["times_used"] += 1
        frac = float(rng.uniform(0.08, 0.22))
        if destroy_name == "random":
            partial = _destroy_random(state, frac, rng)
        elif destroy_name == "related":
            partial = _destroy_related(state, frac, rng)
        elif destroy_name == "high-wtd":
            partial = _destroy_high_wtd(state, current_schedule, frac, rng)
        elif destroy_name == "high-energy":
            partial = _destroy_high_energy(state, frac, rng)
        elif destroy_name == "whole-route":
            partial = _destroy_whole_route(state, rng)
        else:
            partial = _destroy_stop(state, rng)
        candidate, repair_audit = _repair(partial, rng, mode=repair_name, with_audit=True)
        schedule = evaluate_state(candidate, cp_workers=cp_workers,
                                  decoder_time_limit_s=decoder_limit, seed=seed + it + 1)
        audit_row = {"seed": seed, "iteration": it, "destroy": destroy_name,
                     "repair": repair_name, **repair_audit,
                     "multistop_candidates_accepted": 0,
                     "best_multistop_solution_seen": _route_structure_metrics(best_state)["n_multistop_trips"] > 0}
        if schedule is None:
            dw[di] *= 0.995
            rw[ri] *= 0.995
            multistop_audit.append(audit_row)
            continue
        cand_obj = objective(dict(schedule.metrics), normalization, weights)
        was_improvement = cand_obj < cur_obj - 1e-10
        accept = cand_obj <= cur_obj or rng.random() < math.exp(
            -(cand_obj - cur_obj) / max(temperature, 1e-6))
        reward = 0.0
        if accept:
            audit_row["multistop_candidates_accepted"] = int(
                _route_structure_metrics(candidate)["n_multistop_trips"] > 0)
            state, current_schedule, cur_obj = candidate, schedule, cand_obj
            stats[("destroy", destroy_name)]["times_accepted"] += 1
            stats[("repair", repair_name)]["times_accepted"] += 1
            reward = 1.0
            if was_improvement:
                stats[("destroy", destroy_name)]["times_improved"] += 1
                stats[("repair", repair_name)]["times_improved"] += 1
                reward = 3.0
            if cand_obj < objective(dict(best_schedule.metrics), normalization, weights) - 1e-10:
                best_state, best_schedule, reward = candidate, schedule, 5.0
                stats[("destroy", destroy_name)]["times_global_best"] += 1
                stats[("repair", repair_name)]["times_global_best"] += 1
            archive = update_archive(archive, {"seed": seed, "iteration": it,
                                               "metrics": dict(schedule.metrics),
                                               "state": candidate, "schedule": schedule,
                                               "solution_id": f"seed-{seed}-iter-{it}"})
        dw[di] = 0.8 * dw[di] + 0.2 * reward
        rw[ri] = 0.8 * rw[ri] + 0.2 * reward
        if it % 10 == 0 and current_schedule is not None:
            state2, sched2 = _local_stop_search(state, current_schedule,
                                                 cp_workers=cp_workers, seed=seed,
                                                 decoder_time_limit_s=decoder_limit,
                                                 normalization=normalization, weights=weights)
            if sched2 is not None and objective(dict(sched2.metrics), normalization, weights) < cur_obj:
                state, current_schedule = state2, sched2
                cur_obj = objective(dict(sched2.metrics), normalization, weights)
                if cur_obj < objective(dict(best_schedule.metrics), normalization, weights):
                    best_state, best_schedule = state2, sched2
        audit_row["best_multistop_solution_seen"] = _route_structure_metrics(best_state)["n_multistop_trips"] > 0
        multistop_audit.append(audit_row)
        temperature *= 0.995
        hist.append({"iteration": it, "accepted": bool(accept),
                     "objective": float(cur_obj), "n_trips": int(current_schedule.metrics["n_trips"])})
    operator_rows = []
    for (kind, name), row in stats.items():
        row["final_weight"] = float(dw[destroy_names.index(name)] if kind == "destroy"
                                     else rw[repair_names.index(name)])
        operator_rows.append({"seed": seed, "operator_type": kind,
                              "operator_name": name, **row})
    return SeedResult(seed, "PASS", best_state, best_schedule,
                      dict(best_schedule.metrics), hist, archive,
                      time.perf_counter() - started, weight_name=weight_name,
                      operator_stats=operator_rows, multistop_audit=multistop_audit)


def solve_formal_q2(*, seed: int = 20260924, time_limit_s: float = 600.0) -> Q2State:
    """Compatibility API returning only the formal best transport state."""
    return solve_formal(seed, time_limit_s=time_limit_s).state
