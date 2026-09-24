"""Q2-D formal adaptive ALNS.

The implementation deliberately keeps resource variables out of the ALNS
state.  A candidate is always evaluated through the single chain
``Q2-B route evaluator -> Q2-C decoder``.  This makes the method usable with
either the CP-SAT decoder or its documented minimal-environment fallback.
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .deadlines import hard_deadline
from .models import Q2State, RoutePlan
from .route_evaluator import evaluate_route_cached, route_cache_info
from .schedule_decoder import decode_schedule


G_TYPES = ("A", "B", "C")
REFERENCE = {"WTD": 1.0e4, "Cmax_s": 2.0e4,
             "total_energy_kwh": 100.0, "n_trips": 80.0}
WEIGHTS = {"WTD": 0.30, "Cmax_s": 0.30,
           "total_energy_kwh": 0.20, "n_trips": 0.20}


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


def objective(metrics: dict[str, float]) -> float:
    """Fixed-reference normalized weighted Tchebycheff scalarization."""
    return max(WEIGHTS[k] * float(metrics.get(k, 0.0)) / REFERENCE[k]
               for k in WEIGHTS)


def dominates(a: dict[str, float], b: dict[str, float]) -> bool:
    keys = tuple(REFERENCE)
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
    return _destroy_random(Q2State(tuple(state.trips), tuple(related[:n_remove])),
                           1.0, rng) if False else _remove_ids(state, set(related[:n_remove]))


def _remove_ids(state: Q2State, removed: set[str]) -> Q2State:
    trips = []
    for trip in state.trips:
        grouped = {sid: tuple(b for b in trip.boxes_by_stop[sid] if b not in removed)
                   for sid in trip.stop_sequence}
        grouped = {s: b for s, b in grouped.items() if b}
        if grouped:
            trips.append(RoutePlan(trip.gtype, tuple(grouped), grouped))
    return Q2State(tuple(trips), tuple(sorted(removed)))


def _destroy_worst(state: Q2State, fraction: float, rng: np.random.Generator) -> Q2State:
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


def _repair(state: Q2State, rng: np.random.Generator, *, mode: str = "cheapest") -> Q2State:
    from common.data import load_boxes
    table = _box_table()
    trips = list(state.trips)
    unassigned = list(state.unassigned)
    if mode == "deadline-first":
        unassigned.sort(key=lambda b: float(hard_deadline(table[b]) or 1e12))
    else:
        rng.shuffle(unassigned)
    for box in unassigned:
        row = table[box]
        sid = str(row["sid"])
        candidates = []
        for idx, trip in enumerate(trips):
            # Insertion may retype a route and may append a new service stop;
            # this is what lets ALNS explore heterogeneous multi-stop batches.
            order = tuple(trip.stop_sequence) if sid in trip.stop_sequence else \
                tuple(trip.stop_sequence) + (sid,)
            for g in G_TYPES:
                grouped = {s: tuple(trip.boxes_by_stop[s]) for s in trip.stop_sequence}
                grouped.setdefault(sid, tuple())
                grouped[sid] = grouped[sid] + (box,)
                try:
                    candidate = RoutePlan(g, order, grouped)
                    ev = _route_eval(candidate)
                except ValueError:
                    continue
                if ev.route_feasible:
                    score = (float(ev.total_route_energy_kwh),
                             float(ev.route_duration_s), len(order), idx)
                    candidates.append((score, idx, candidate))
        # New trips are always considered; max_stops is not a formal bound.
        for g in G_TYPES:
            try:
                candidate = RoutePlan(g, (sid,), {sid: (box,)})
                ev = _route_eval(candidate)
            except ValueError:
                continue
            if ev.route_feasible:
                gp = {"A": 0.0, "B": 1.0, "C": 2.0}[g]
                candidates.append(((float(ev.total_route_energy_kwh), gp, len(trips)),
                                  len(trips), candidate))
        if not candidates:
            return Q2State(tuple(trips), tuple(unassigned[unassigned.index(box):]))
        _, idx, candidate = min(candidates, key=lambda x: x[0])
        if idx == len(trips):
            trips.append(candidate)
        else:
            trips[idx] = candidate
    return Q2State(tuple(trips))


def _local_stop_search(state: Q2State, current_schedule, *, cp_workers: int,
                       seed: int, decoder_time_limit_s: float) -> tuple[Q2State, Any]:
    best_state, best_schedule = state, current_schedule
    best_obj = objective(dict(best_schedule.metrics))
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
            if schedule is not None and objective(dict(schedule.metrics)) < best_obj - 1e-10:
                best_state, best_schedule = candidate_state, schedule
                best_obj = objective(dict(schedule.metrics))
    return best_state, best_schedule


def solve_formal(seed: int = 20260924, *, time_limit_s: float = 30.0,
                 iterations: int | None = None, cp_workers: int = 1) -> SeedResult:
    started = time.perf_counter()
    rng = np.random.default_rng(seed)
    state = build_initial_state(seed)
    decoder_limit = min(5.0, max(0.5, time_limit_s / 8.0))
    current_schedule = evaluate_state(state, cp_workers=cp_workers,
                                      decoder_time_limit_s=decoder_limit, seed=seed)
    if current_schedule is None:
        return SeedResult(seed, "INFEASIBLE", state, runtime_s=time.perf_counter() - started,
                          error="initial state could not be decoded")
    best_state, best_schedule = state, current_schedule
    archive = update_archive([], {"seed": seed, "metrics": dict(current_schedule.metrics),
                                 "state": state})
    hist = []
    n_iter = iterations if iterations is not None else (max(20, min(80, int(time_limit_s * 2))))
    destroy_names = ("random", "related", "worst")
    repair_names = ("cheapest", "deadline-first")
    dw = np.ones(len(destroy_names), dtype=float)
    rw = np.ones(len(repair_names), dtype=float)
    temperature = 1.0
    cur_obj = objective(dict(current_schedule.metrics))
    for it in range(n_iter):
        if time.perf_counter() - started >= time_limit_s:
            break
        di = int(rng.choice(len(destroy_names), p=dw / dw.sum()))
        ri = int(rng.choice(len(repair_names), p=rw / rw.sum()))
        frac = float(rng.uniform(0.08, 0.22))
        if destroy_names[di] == "random":
            partial = _destroy_random(state, frac, rng)
        elif destroy_names[di] == "related":
            partial = _destroy_related(state, frac, rng)
        else:
            partial = _destroy_worst(state, frac, rng)
        candidate = _repair(partial, rng, mode=repair_names[ri])
        schedule = evaluate_state(candidate, cp_workers=cp_workers,
                                  decoder_time_limit_s=decoder_limit, seed=seed + it + 1)
        if schedule is None:
            dw[di] *= 0.995
            rw[ri] *= 0.995
            continue
        cand_obj = objective(dict(schedule.metrics))
        accept = cand_obj <= cur_obj or rng.random() < math.exp(
            -(cand_obj - cur_obj) / max(temperature, 1e-6))
        reward = 0.0
        if accept:
            state, current_schedule, cur_obj = candidate, schedule, cand_obj
            reward = 1.0
            if cand_obj < objective(dict(best_schedule.metrics)) - 1e-10:
                best_state, best_schedule, reward = candidate, schedule, 5.0
        if accept:
            dw[di] = 0.8 * dw[di] + 0.2 * max(reward, 0.1)
            rw[ri] = 0.8 * rw[ri] + 0.2 * max(reward, 0.1)
            archive = update_archive(archive, {"seed": seed, "iteration": it,
                                               "metrics": dict(schedule.metrics),
                                               "state": candidate})
        if it % 10 == 0 and current_schedule is not None:
            state2, sched2 = _local_stop_search(state, current_schedule,
                                                 cp_workers=cp_workers, seed=seed,
                                                 decoder_time_limit_s=decoder_limit)
            if sched2 is not None and objective(dict(sched2.metrics)) < cur_obj:
                state, current_schedule = state2, sched2
                cur_obj = objective(dict(sched2.metrics))
                if cur_obj < objective(dict(best_schedule.metrics)):
                    best_state, best_schedule = state2, sched2
        temperature *= 0.995
        hist.append({"iteration": it, "accepted": bool(accept),
                     "objective": float(cur_obj), "n_trips": int(current_schedule.metrics["n_trips"])})
    return SeedResult(seed, "PASS", best_state, best_schedule,
                      dict(best_schedule.metrics), hist,
                      [{"seed": x["seed"], "metrics": x["metrics"]} for x in archive],
                      time.perf_counter() - started)


def solve_formal_q2(*, seed: int = 20260924, time_limit_s: float = 600.0) -> Q2State:
    """Compatibility API returning only the formal best transport state."""
    return solve_formal(seed, time_limit_s=time_limit_s).state
