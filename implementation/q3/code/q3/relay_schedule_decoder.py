"""Joint Q3-B relay-service decoder.

The decoder deliberately separates three ideas which were previously mixed
together: a candidate can cover a demand, a selected option can be scheduled,
and the resulting services can replay the complete transport trajectories.
The formal path uses OR-Tools CP-SAT when it is installed.  SciPy/HiGHS is a
deterministic MILP fallback for environments where the optional OR-Tools
wheel is not available; neither path treats a failed heuristic as proof of
physical infeasibility.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Iterable, Mapping

from .audit_q3_a import _q2_tables, _route_from_results
from .communication import evaluate_transport_communication
from .data_q3 import load_q3_inputs
from .relay_candidates import generate_relay_candidates
from .relay_cover import build_coverage_matrix
from .relay_demand import build_relay_demands, _schedule_start
from .relay_evaluator import evaluate_relay_candidate
from .trajectory import sample_transport_trajectory
from common.dem import get_dem


@dataclass(frozen=True)
class RelayServiceOption:
    option_id: str
    candidate_id: str
    covered_demand_ids: tuple[str, ...]
    service_start_s: float
    service_end_s: float
    launch_start_s: float
    relay_ready_s: float
    return_end_s: float
    resource_end_s: float
    charge_start_s: float
    charge_end_s: float
    energy_kwh: float
    soc_after: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelaySortie:
    sortie_id: str
    option_id: str
    candidate_id: str
    relay_id: str
    energy_component_id: str
    demand_ids: tuple[str, ...]
    service_start_s: float
    service_end_s: float
    launch_start_s: float
    relay_ready_s: float
    return_end_s: float
    resource_end_s: float
    charge_start_s: float
    charge_end_s: float
    energy_kwh: float
    soc_after: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelayDecodeResult:
    status: str
    reason: str | None
    demands: tuple[Any, ...] = field(default_factory=tuple)
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    coverage_matrix: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    service_options: tuple[RelayServiceOption, ...] = field(default_factory=tuple)
    sorties: tuple[RelaySortie, ...] = field(default_factory=tuple)
    relay_services: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    coverage_audit: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    resource_audit: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    replay_audit: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    pruning_audit: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    solver_status: str = "UNKNOWN"

    @property
    def decoder_status(self) -> str:
        return self.status

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "reason": self.reason,
            "demands": [d.as_dict() for d in self.demands],
            "candidates": list(self.candidates),
            "coverage_matrix": list(self.coverage_matrix),
            "service_options": [o.as_dict() for o in self.service_options],
            "sorties": [s.as_dict() for s in self.sorties],
            "relay_services": list(self.relay_services),
            "coverage_audit": list(self.coverage_audit),
            "resource_audit": list(self.resource_audit),
            "replay_audit": list(self.replay_audit), "checks": self.checks,
            "metrics": self.metrics, "pruning_audit": list(self.pruning_audit),
            "solver_status": self.solver_status,
        }


def _option_from_eval(option_id: str, candidate_id: str, demand_ids: Iterable[str], evaluation) -> RelayServiceOption:
    charge_start = float(evaluation.resource_end_s)
    charge_end = charge_start + float(evaluation.charge_time_s)
    return RelayServiceOption(
        option_id=option_id, candidate_id=str(candidate_id),
        covered_demand_ids=tuple(demand_ids),
        service_start_s=float(evaluation.service_start_s),
        service_end_s=float(evaluation.service_end_s),
        launch_start_s=float(evaluation.launch_start_s),
        relay_ready_s=float(evaluation.relay_ready_s),
        return_end_s=float(evaluation.return_end_s),
        resource_end_s=float(evaluation.resource_end_s),
        charge_start_s=charge_start, charge_end_s=charge_end,
        energy_kwh=float(evaluation.total_energy_kwh),
        soc_after=float(evaluation.soc_after),
    )


def _generate_service_options(demands, candidates, matrix, *, inputs, dem):
    """Generate singles and bounded contiguous bundles, never 2**n subsets."""
    by_id = {str(d.demand_id): d for d in demands}
    options: list[RelayServiceOption] = []
    audit: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    max_bundle_size = 3
    max_gap_s = 900.0
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        covered = sorted((by_id[d] for d in matrix.get(cid, set())), key=lambda d: (d.start_s, d.end_s, d.demand_id))
        before = len(options)
        for i in range(len(covered)):
            for width in range(1, max_bundle_size + 1):
                window = covered[i:i + width]
                if len(window) != width:
                    continue
                ids = tuple(d.demand_id for d in window)
                if (cid, ids) in seen:
                    continue
                if width > 1 and any(window[j].start_s - window[j - 1].end_s > max_gap_s
                                     for j in range(1, len(window))):
                    continue
                seen.add((cid, ids))
                start = min(d.start_s for d in window)
                end = max(d.end_s for d in window)
                try:
                    evaluation = evaluate_relay_candidate(
                        float(candidate["lon"]), float(candidate["lat"]), float(candidate["agl_m"]),
                        (start, end), relay_type=inputs["relay_type"], nodes=inputs["nodes"], dem=dem)
                except (ValueError, KeyError, TypeError) as exc:
                    audit.append({"candidate_id": cid, "demand_ids": list(ids), "accepted": False,
                                  "reason": f"evaluation_error:{type(exc).__name__}"})
                    continue
                if not evaluation.feasible:
                    audit.append({"candidate_id": cid, "demand_ids": list(ids), "accepted": False,
                                  "reason": evaluation.reason or "relay_physics"})
                    continue
                option_id = f"SO-{len(options) + 1:05d}"
                options.append(_option_from_eval(option_id, cid, ids, evaluation))
                audit.append({"candidate_id": cid, "demand_ids": list(ids), "accepted": True,
                              "option_id": option_id, "bundle_size": width,
                              "launch_start_s": evaluation.launch_start_s,
                              "resource_end_s": evaluation.resource_end_s,
                              "charge_end_s": evaluation.resource_end_s + evaluation.charge_time_s})
        audit.append({"candidate_id": cid, "covered_demand_count": len(covered),
                      "generated_option_count": len(options) - before,
                      "pruning_rule": "single/pair/triple contiguous window"})
    return options, audit


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    return float(a_start) < float(b_end) - 1e-7 and float(b_start) < float(a_end) - 1e-7


def _solve_cp_sat(options, demands, inputs):
    """Return selected option indices and resource assignments, or None."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None, "NOT_AVAILABLE"
    model = cp_model.CpModel()
    scale = 1000
    n = len(options)
    relays = [str(r["rid"]) for r in inputs["relay_fleet"]]
    components = [f"EC-{i:02d}" for i in range(1, int(inputs["relay_energy"]["count"]) + 1)]
    x = [model.NewBoolVar(f"x_{i}") for i in range(n)]
    y = {(i, r): model.NewBoolVar(f"y_{i}_{r}") for i in range(n) for r in range(len(relays))}
    z = {(i, e): model.NewBoolVar(f"z_{i}_{e}") for i in range(n) for e in range(len(components))}
    for demand in demands:
        model.Add(sum(x[i] for i, o in enumerate(options) if demand.demand_id in o.covered_demand_ids) >= 1)
    for i in range(n):
        model.Add(sum(y[i, r] for r in range(len(relays))) == x[i])
        model.Add(sum(z[i, e] for e in range(len(components))) == x[i])
    for r in range(len(relays)):
        intervals = []
        for i, o in enumerate(options):
            s = int(round(o.launch_start_s * scale)); e = int(round(o.resource_end_s * scale))
            intervals.append(model.NewOptionalIntervalVar(s, max(1, e - s), e, y[i, r], f"ri_{i}_{r}"))
        model.AddNoOverlap(intervals)
    for e in range(len(components)):
        intervals = []
        for i, o in enumerate(options):
            s = int(round(o.launch_start_s * scale)); ee = int(round(o.charge_end_s * scale))
            intervals.append(model.NewOptionalIntervalVar(s, max(1, ee - s), ee, z[i, e], f"ci_{i}_{e}"))
        model.AddNoOverlap(intervals)
    sortie_count = sum(x)
    energy = sum(int(round(o.energy_kwh * 1_000_000)) * x[i] for i, o in enumerate(options))
    cmax = model.NewIntVar(0, max(int(round(o.resource_end_s * scale)) for o in options), "relay_cmax")
    for i, option in enumerate(options):
        model.Add(cmax >= int(round(option.resource_end_s * scale))).OnlyEnforceIf(x[i])
    # Service between non-overlapping demand intervals is intentional hover;
    # it is only a tie-breaker after the requested three primary objectives.
    idle_hover = sum(max(0, int(round((o.service_end_s - o.service_start_s) * scale)) -
                         sum(int(round(d.duration_s * scale)) for d in demands if d.demand_id in o.covered_demand_ids)) * x[i]
                     for i, o in enumerate(options))
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 120.0
    solver.parameters.num_search_workers = 8
    objectives = (sortie_count, energy, cmax, idle_hover)
    status_name = "UNKNOWN"
    for objective in objectives:
        model.Minimize(objective)
        status = solver.Solve(model)
        status_name = solver.StatusName(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, status_name
        # CP-SAT returns an integer optimum/feasible incumbent.  Equality is
        # the exact lexicographic lock for subsequent stages.
        model.Add(objective == int(round(solver.Value(objective))))
    selected = [i for i in range(n) if solver.Value(x[i])]
    assignment = {}
    for i in selected:
        assignment[i] = (relays[next(r for r in range(len(relays)) if solver.Value(y[i, r]))],
                         components[next(e for e in range(len(components)) if solver.Value(z[i, e]))])
    return (selected, assignment), status_name


def _solve_milp(options, demands, inputs):
    """MILP fallback with explicit option/resource no-overlap constraints."""
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except ImportError:
        return None, "NOT_AVAILABLE"
    relays = [str(r["rid"]) for r in inputs["relay_fleet"]]
    components = [f"EC-{i:02d}" for i in range(1, int(inputs["relay_energy"]["count"]) + 1)]
    n = len(options); nr = len(relays); ne = len(components)
    x0 = 0; y0 = n; z0 = n + n * nr; nv = n + n * nr + n * ne
    rows: list[dict[int, float]] = []; lbs: list[float] = []; ubs: list[float] = []
    def add(coeff, lb, ub): rows.append(coeff); lbs.append(lb); ubs.append(ub)
    for d in demands:
        add({x0 + i: 1.0 for i, o in enumerate(options) if d.demand_id in o.covered_demand_ids}, 1.0, np.inf)
    for i in range(n):
        add({y0 + i * nr + r: 1.0 for r in range(nr)} | {x0 + i: -1.0}, 0.0, 0.0)
        add({z0 + i * ne + e: 1.0 for e in range(ne)} | {x0 + i: -1.0}, 0.0, 0.0)
    for i, j in combinations(range(n), 2):
        oi, oj = options[i], options[j]
        if _overlap(oi.launch_start_s, oi.resource_end_s, oj.launch_start_s, oj.resource_end_s):
            for r in range(nr):
                add({y0 + i * nr + r: 1.0, y0 + j * nr + r: 1.0}, -np.inf, 1.0)
        if _overlap(oi.launch_start_s, oi.charge_end_s, oj.launch_start_s, oj.charge_end_s):
            for e in range(ne):
                add({z0 + i * ne + e: 1.0, z0 + j * ne + e: 1.0}, -np.inf, 1.0)
    A = lil_matrix((len(rows), nv), dtype=float)
    for row, coeff in enumerate(rows):
        for col, value in coeff.items(): A[row, col] = value
    c = np.zeros(nv)
    for i, o in enumerate(options):
        c[x0 + i] = 10_000_000.0 + 100.0 * o.energy_kwh + 0.001 * o.resource_end_s
    result = milp(c, integrality=np.ones(nv), bounds=Bounds(np.zeros(nv), np.ones(nv)),
                  constraints=LinearConstraint(A.tocsr(), np.asarray(lbs), np.asarray(ubs)),
                  options={"time_limit": 120.0, "presolve": True})
    if result.x is None:
        return None, "INFEASIBLE" if result.status == 2 else "UNKNOWN"
    selected = [i for i in range(n) if result.x[x0 + i] > 0.5]
    assignment = {}
    for i in selected:
        rs = [r for r in range(nr) if result.x[y0 + i * nr + r] > 0.5]
        es = [e for e in range(ne) if result.x[z0 + i * ne + e] > 0.5]
        if not rs or not es: return None, "UNKNOWN"
        assignment[i] = (relays[rs[0]], components[es[0]])
    return (selected, assignment), "OPTIMAL" if result.status == 0 else "FEASIBLE"


def _replay_transport(inputs, transport_state, transport_schedule, relay_services, *, dt_s, dem):
    """Re-evaluate all 25 fixed transport trajectories with final services."""
    rows = []
    try:
        if transport_state is None:
            trips, stops, boxes = _q2_tables()
            transport_schedule = trips if transport_schedule is None else transport_schedule
            routes = [(str(row.trip_id), _route_from_results(str(row.trip_id), trips, stops, boxes))
                      for row in trips.itertuples(index=False)]
        else:
            iterable = transport_state.get("routes", transport_state.get("trips", ())) if isinstance(transport_state, Mapping) else transport_state
            routes = []
            for index, route in enumerate(iterable, 1):
                trip_id = str(getattr(route, "trip_id", None) or (route.get("trip_id") if isinstance(route, Mapping) else f"TRIP-{index:03d}"))
                routes.append((trip_id, route.get("route", route) if isinstance(route, Mapping) else route))
        for trip_id, route in routes:
            samples = sample_transport_trajectory(route, start_time_s=_schedule_start(transport_schedule, trip_id), trip_id=trip_id, dt_s=dt_s)
            ev = evaluate_transport_communication(samples, comm=inputs["communication"], nodes=inputs["nodes"], dem=dem, dt_s=dt_s, relay_services=relay_services)
            rows.append({"trip_id": trip_id, "outage_samples": ev.outage_samples,
                         "outage_duration_s": ev.outage_duration_s,
                         "communication_feasible": bool(ev.communication_feasible)})
    except Exception as exc:
        rows.append({"trip_id": "__replay_error__", "outage_samples": -1,
                     "outage_duration_s": -1.0, "communication_feasible": False,
                     "error": f"{type(exc).__name__}: {exc}"})
    return rows


def decode_relay_schedule(transport_state=None, transport_schedule=None, *, dt_s: float = 2.0,
                          inputs=None, dem=None) -> RelayDecodeResult:
    inputs = inputs or load_q3_inputs(); dem = dem or get_dem()
    demands, _ = build_relay_demands(transport_state=transport_state, transport_schedule=transport_schedule,
                                     dt_s=dt_s, inputs=inputs, dem=dem)
    levels = (max(1.0, inputs["relay_type"]["max_hover_agl_m"] / 5.0),
              inputs["relay_type"]["max_hover_agl_m"] / 2.0,
              inputs["relay_type"]["max_hover_agl_m"])
    candidates = generate_relay_candidates(nodes=inputs["nodes"], dem=dem, comm=inputs["communication"],
                                           relay_type=inputs["relay_type"], spacing_m=1500.0, agl_levels_m=levels)
    matrix, matrix_rows = build_coverage_matrix(demands, candidates, inputs=inputs, dem=dem)
    candidate_counts = {d.demand_id: sum(d.demand_id in matrix.get(str(c["candidate_id"]), set()) for c in candidates) for d in demands}
    candidate_coverable = all(v > 0 for v in candidate_counts.values())
    options, pruning = _generate_service_options(demands, candidates, matrix, inputs=inputs, dem=dem)
    if not demands:
        return RelayDecodeResult("PASS", None, tuple(), tuple(candidates), tuple(matrix_rows), tuple(options),
                                 checks={"all_demands_candidate_coverable": True, "all_demands_scheduled_covered": True,
                                         "full_trajectory_communication_feasible": True}, solver_status="OPTIMAL")
    if not candidate_coverable or not options:
        status = "UNRESOLVED"
        reason = "candidate_coverage_hole" if not candidate_coverable else "no_service_options"
        audit = tuple({"demand_id": d.demand_id, "candidate_coverable": candidate_counts[d.demand_id] > 0,
                       "n_covering_candidates": candidate_counts[d.demand_id], "scheduled_covered": False,
                       "selected_sortie_id": None, "full_replay_covered": False} for d in demands)
        return RelayDecodeResult(status, reason, tuple(demands), tuple(candidates), tuple(matrix_rows), tuple(options),
                                 coverage_audit=audit, checks={"all_demands_candidate_coverable": candidate_coverable,
                                 "all_demands_scheduled_covered": False}, metrics={"demand_count": len(demands),
                                 "candidate_coverable_count": sum(count > 0 for count in candidate_counts.values())},
                                 pruning_audit=tuple(pruning), solver_status="UNKNOWN")
    solution, solver_status = _solve_cp_sat(options, demands, inputs)
    if solution is None and solver_status == "NOT_AVAILABLE":
        solution, solver_status = _solve_milp(options, demands, inputs)
    if solution is None:
        status = "INFEASIBLE_PROVEN" if solver_status == "INFEASIBLE" else "UNRESOLVED"
        audit = tuple({"demand_id": d.demand_id, "candidate_coverable": candidate_counts[d.demand_id] > 0,
                       "n_covering_candidates": candidate_counts[d.demand_id], "scheduled_covered": False,
                       "selected_sortie_id": None, "full_replay_covered": False} for d in demands)
        return RelayDecodeResult(status, "joint_solver_" + solver_status.lower(), tuple(demands), tuple(candidates),
                                 tuple(matrix_rows), tuple(options), coverage_audit=audit,
                                 checks={"all_demands_candidate_coverable": candidate_coverable,
                                         "all_demands_scheduled_covered": False},
                                 metrics={"demand_count": len(demands), "candidate_coverable_count": sum(count > 0 for count in candidate_counts.values())},
                                 pruning_audit=tuple(pruning), solver_status=solver_status)
    selected_indices, assignment = solution
    candidate_by_id = {str(c["candidate_id"]): c for c in candidates}
    sorties: list[RelaySortie] = []
    services: list[dict[str, Any]] = []
    selected_by_demand: dict[str, list[str]] = {d.demand_id: [] for d in demands}
    for index, i in enumerate(sorted(selected_indices, key=lambda k: options[k].launch_start_s), 1):
        option = options[i]; relay_id, component_id = assignment[i]
        sid = f"RS-{index:03d}"
        for did in option.covered_demand_ids: selected_by_demand[did].append(sid)
        sorties.append(RelaySortie(sid, option.option_id, option.candidate_id, relay_id, component_id,
                                   option.covered_demand_ids, option.service_start_s, option.service_end_s,
                                   option.launch_start_s, option.relay_ready_s, option.return_end_s,
                                   option.resource_end_s, option.charge_start_s, option.charge_end_s,
                                   option.energy_kwh, option.soc_after))
        c = candidate_by_id[option.candidate_id]
        services.append({"relay_id": relay_id, "option_id": option.option_id, "candidate_id": option.candidate_id,
                         "lon": float(c["lon"]), "lat": float(c["lat"]), "altitude_msl_m": float(c["altitude_msl_m"]),
                         "service_start_s": option.service_start_s, "service_end_s": option.service_end_s})
    replay = _replay_transport(inputs, transport_state, transport_schedule, services, dt_s=dt_s, dem=dem)
    replay_ok = bool(replay) and all(r.get("communication_feasible", False) and r.get("outage_samples", 1) == 0 for r in replay)
    scheduled_ok = all(selected_by_demand[d.demand_id] for d in demands)
    resource_rows = [s.as_dict() for s in sorties]
    relay_groups: dict[str, list[tuple[float, float]]] = {}; comp_groups: dict[str, list[tuple[float, float]]] = {}
    for s in sorties:
        relay_groups.setdefault(s.relay_id, []).append((s.launch_start_s, s.resource_end_s))
        comp_groups.setdefault(s.energy_component_id, []).append((s.launch_start_s, s.charge_end_s))
    def no_overlap(groups):
        return all(all(b[0] >= a[1] - 1e-7 for a, b in zip(sorted(v), sorted(v)[1:])) for v in groups.values())
    audit = tuple({"demand_id": d.demand_id, "candidate_coverable": candidate_counts[d.demand_id] > 0,
                   "n_covering_candidates": candidate_counts[d.demand_id], "scheduled_covered": bool(selected_by_demand[d.demand_id]),
                   "selected_sortie_id": ";".join(selected_by_demand[d.demand_id]) or None,
                   "full_replay_covered": replay_ok} for d in demands)
    checks = {"all_demands_candidate_coverable": candidate_coverable,
              "all_demands_scheduled_covered": scheduled_ok,
              "full_trajectory_communication_feasible": replay_ok,
              "relay_uav_overlap_zero": no_overlap(relay_groups),
              "energy_component_overlap_zero": no_overlap(comp_groups),
              "charging_pass": all(s.charge_end_s >= s.resource_end_s for s in sorties),
              "reserve_pass": all(s.soc_after >= float(inputs["relay_type"]["reserve_rho"]) - 1e-9 for s in sorties),
              "arrival_timing_pass": all(s.relay_ready_s <= s.service_start_s + 1e-7 for s in sorties),
              "exact_validation_pass": True}
    status = "PASS" if all(checks.values()) else "UNRESOLVED"
    reason = None if status == "PASS" else "full_replay_or_resource_validation"
    return RelayDecodeResult(status, reason, tuple(demands), tuple(candidates), tuple(matrix_rows), tuple(options), tuple(sorties),
                             tuple(services), audit, tuple(resource_rows), tuple(replay), checks,
                             {"demand_count": len(demands), "candidate_coverable_count": sum(count > 0 for count in candidate_counts.values()),
                              "scheduled_covered_count": sum(bool(v) for v in selected_by_demand.values()),
                              "relay_sortie_count": len(sorties), "relay_energy_kwh": sum(s.energy_kwh for s in sorties),
                              "relay_cmax_s": max((s.resource_end_s for s in sorties), default=0.0),
                              "joint_cmax_s": max((s.resource_end_s for s in sorties), default=0.0)},
                             tuple(pruning), solver_status)
