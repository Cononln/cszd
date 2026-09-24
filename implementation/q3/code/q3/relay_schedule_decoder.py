"""Greedy Q3-B relay decoder with resource-feasible sortie construction."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from .data_q3 import load_q3_inputs
from .relay_candidates import generate_relay_candidates
from .relay_cover import build_coverage_matrix, strict_replay_coverage
from .relay_demand import build_relay_demands
from .relay_evaluator import evaluate_relay_candidate, validate_relay_resource_schedule
from .trajectory import sample_transport_trajectory
from .communication import evaluate_transport_communication
from .audit_q3_a import _q2_tables, _route_from_results
from common.dem import get_dem


@dataclass(frozen=True)
class RelaySortie:
    sortie_id: str
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

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RelayDecodeResult:
    status: str
    reason: str | None
    demands: tuple[Any, ...] = field(default_factory=tuple)
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    coverage_matrix: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    sorties: tuple[RelaySortie, ...] = field(default_factory=tuple)
    relay_services: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    pruning_audit: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self):
        return {"status": self.status, "reason": self.reason,
                "demands": [d.as_dict() for d in self.demands],
                "candidates": list(self.candidates), "coverage_matrix": list(self.coverage_matrix),
                "sorties": [s.as_dict() for s in self.sorties],
                "relay_services": list(self.relay_services), "checks": self.checks, "metrics": self.metrics}


def _clusters_for_candidate(demands, covered_ids):
    selected = sorted((d for d in demands if d.demand_id in covered_ids), key=lambda d: d.start_s)
    clusters = []
    current = []
    end = None
    for demand in selected:
        if current and demand.start_s > float(end) + 1e-6:
            clusters.append(current)
            current = []
        current.append(demand)
        end = max(float(end or demand.end_s), demand.end_s)
    if current:
        clusters.append(current)
    return clusters


def _schedule_sortie(cluster, candidate, *, relay_type, inputs, dem, sortie_id, relay_id, component_id):
    start = min(d.start_s for d in cluster)
    end = max(d.end_s for d in cluster)
    evaluation = evaluate_relay_candidate(float(candidate["lon"]), float(candidate["lat"]), float(candidate["agl_m"]),
                                          (start, end), relay_type=relay_type, nodes=inputs["nodes"], dem=dem)
    if not evaluation.feasible:
        return None
    charge_start = evaluation.resource_end_s
    charge_end = charge_start + evaluation.charge_time_s
    return RelaySortie(sortie_id=sortie_id, candidate_id=str(candidate["candidate_id"]), relay_id=relay_id,
                       energy_component_id=component_id, demand_ids=tuple(d.demand_id for d in cluster),
                       service_start_s=start, service_end_s=end, launch_start_s=evaluation.launch_start_s,
                       relay_ready_s=evaluation.relay_ready_s, return_end_s=evaluation.return_end_s,
                       resource_end_s=evaluation.resource_end_s, charge_start_s=charge_start,
                       charge_end_s=charge_end, energy_kwh=evaluation.total_energy_kwh,
                       soc_after=evaluation.soc_after)


def decode_relay_schedule(transport_state=None, transport_schedule=None, *, dt_s: float = 2.0,
                          inputs=None, dem=None) -> RelayDecodeResult:
    inputs = inputs or load_q3_inputs()
    dem = dem or get_dem()
    demands, demand_audit = build_relay_demands(transport_state=transport_state,
                                                transport_schedule=transport_schedule,
                                                dt_s=dt_s, inputs=inputs, dem=dem)
    levels = (max(1.0, inputs["relay_type"]["max_hover_agl_m"] / 5.0),
              inputs["relay_type"]["max_hover_agl_m"] / 2.0,
              inputs["relay_type"]["max_hover_agl_m"])
    candidates = generate_relay_candidates(nodes=inputs["nodes"], dem=dem, comm=inputs["communication"],
                                           relay_type=inputs["relay_type"], spacing_m=1500.0, agl_levels_m=levels)
    matrix, matrix_rows = build_coverage_matrix(demands, candidates, inputs=inputs, dem=dem)
    uncovered = {str(d.demand_id) for d in demands}
    chosen: list[tuple[dict[str, Any], list[Any]]] = []
    pruning = [{"candidate_id": str(c["candidate_id"]), "selected": False,
                "covered_demand_count": len(matrix.get(str(c["candidate_id"]), set())),
                "reason": "candidate_coverage_audit"} for c in candidates]
    while uncovered:
        feasible_options = []
        for candidate in candidates:
            cid = str(candidate["candidate_id"])
            cover = uncovered.intersection(matrix.get(cid, set()))
            if not cover:
                continue
            for cluster in _clusters_for_candidate(demands, cover):
                if not cluster:
                    continue
                evaluation = evaluate_relay_candidate(float(candidate["lon"]), float(candidate["lat"]),
                                                      float(candidate["agl_m"]),
                                                      (min(d.start_s for d in cluster), max(d.end_s for d in cluster)),
                                                      relay_type=inputs["relay_type"], nodes=inputs["nodes"], dem=dem)
                if evaluation.feasible:
                    feasible_options.append((len({d.demand_id for d in cluster} & uncovered), candidate, cluster))
        if not feasible_options:
            return RelayDecodeResult("INFEASIBLE", "coverage_hole_or_relay_energy", tuple(demands), tuple(candidates),
                                     tuple(matrix_rows), checks={"all_demands_covered": False},
                                     metrics={"demand_count": len(demands), "covered_demand_count": len(demands) - len(uncovered)},
                                     pruning_audit=tuple(pruning))
        gain, candidate, cluster = max(feasible_options, key=lambda item: (item[0], -float(item[1]["energy_margin_at_60s_kwh"])))
        ids = {d.demand_id for d in cluster} & uncovered
        chosen.append((candidate, [d for d in cluster if d.demand_id in ids]))
        uncovered -= ids
        for row in pruning:
            if row["candidate_id"] == str(candidate["candidate_id"]):
                row.update({"selected": True, "newly_covered": len(ids),
                            "remaining_uncovered": len(uncovered), "reason": "greedy_gain"})
    sorties: list[RelaySortie] = []
    relay_available = {str(row["rid"]): 0.0 for row in inputs["relay_fleet"]}
    component_available = {f"EC-{i:02d}": 0.0 for i in range(1, int(inputs["relay_energy"]["count"]) + 1)}
    for index, (candidate, cluster) in enumerate(sorted(chosen, key=lambda x: min(d.start_s for d in x[1])), 1):
        start = min(d.start_s for d in cluster)
        feasible_assignments = []
        for relay_id, available in relay_available.items():
            for component_id, component_free in component_available.items():
                if max(available, component_free) <= start + 1e-6:
                    feasible_assignments.append((max(available, component_free), relay_id, component_id))
        if not feasible_assignments:
            return RelayDecodeResult("INFEASIBLE", "relay_uav_or_energy_component_overlap", tuple(demands), tuple(candidates),
                                     tuple(matrix_rows), checks={"all_demands_covered": True, "resources": False},
                                     metrics={"demand_count": len(demands)}, pruning_audit=tuple(pruning))
        _, relay_id, component_id = min(feasible_assignments)
        sortie = _schedule_sortie(cluster, candidate, relay_type=inputs["relay_type"], inputs=inputs, dem=dem,
                                  sortie_id=f"RS-{index:03d}", relay_id=relay_id, component_id=component_id)
        if sortie is None:
            return RelayDecodeResult("INFEASIBLE", "relay_energy_or_arrival_timing", tuple(demands), tuple(candidates),
                                     tuple(matrix_rows), checks={"all_demands_covered": True, "resources": False},
                                     pruning_audit=tuple(pruning))
        sorties.append(sortie)
        relay_available[relay_id] = sortie.resource_end_s
        component_available[component_id] = sortie.charge_end_s
    services = []
    candidate_by_id = {str(c["candidate_id"]): c for c in candidates}
    for sortie in sorties:
        c = candidate_by_id[sortie.candidate_id]
        services.append({"relay_id": sortie.relay_id, "candidate_id": sortie.candidate_id,
                         "lon": float(c["lon"]), "lat": float(c["lat"]), "altitude_msl_m": float(c["altitude_msl_m"]),
                         "service_start_s": sortie.service_start_s, "service_end_s": sortie.service_end_s})
    resource_rows = [{**s.as_dict(), "energy_component_id": s.energy_component_id} for s in sorties]
    resource = validate_relay_resource_schedule(resource_rows)
    checks = {"all_demands_covered": not uncovered, "relay_uav_overlap_zero": resource["relay_uav_overlap_zero"],
              "energy_component_overlap_zero": resource["energy_component_overlap_zero"],
              "arrival_before_demand": all(s.relay_ready_s <= s.service_start_s + 1e-6 for s in sorties),
              "reserve_soc_pass": all(s.soc_after >= float(inputs["relay_type"]["reserve_rho"]) - 1e-9 for s in sorties)}
    status = "PASS" if all(checks.values()) else "INFEASIBLE"
    return RelayDecodeResult(status, None if status == "PASS" else "resource_validation", tuple(demands), tuple(candidates),
                             tuple(matrix_rows), tuple(sorties), tuple(services), checks,
                             {"demand_count": len(demands), "relay_sortie_count": len(sorties),
                              "relay_energy_kwh": sum(s.energy_kwh for s in sorties),
                              "relay_cmax_s": max((s.resource_end_s for s in sorties), default=0.0),
                              "joint_cmax_s": max((s.resource_end_s for s in sorties), default=0.0)},
                             tuple(pruning))
