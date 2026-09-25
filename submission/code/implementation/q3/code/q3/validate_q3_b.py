"""Independent Q3-B verification and fully enumerated small exact cases."""
from __future__ import annotations

from itertools import combinations, product

from .communication import evaluate_transport_communication
from .data_q3 import load_q3_inputs
from .relay_cover import strict_replay_coverage
from .relay_schedule_decoder import _replay_transport, decode_relay_schedule
from common.dem import get_dem


def _no_overlap(intervals):
    ordered = sorted((float(a), float(b)) for a, b in intervals)
    return all(right[0] >= left[1] - 1e-7 for left, right in zip(ordered, ordered[1:]))


def _enumerate_exact(demands, options, *, n_relays, n_components):
    """Complete subset-and-assignment enumeration for deliberately tiny cases."""
    best = None
    for n_selected in range(1, len(options) + 1):
        for subset in combinations(range(len(options)), n_selected):
            if not set(demands).issubset(set().union(*(set(options[i]["covers"]) for i in subset))):
                continue
            for relay_choice in product(range(n_relays), repeat=n_selected):
                relay_intervals = {r: [] for r in range(n_relays)}
                for local, option_index in enumerate(subset):
                    option = options[option_index]
                    relay_intervals[relay_choice[local]].append((option["launch"], option["resource_end"]))
                if not all(_no_overlap(v) for v in relay_intervals.values()):
                    continue
                for component_choice in product(range(n_components), repeat=n_selected):
                    component_intervals = {e: [] for e in range(n_components)}
                    for local, option_index in enumerate(subset):
                        option = options[option_index]
                        component_intervals[component_choice[local]].append((option["launch"], option["charge_end"]))
                    if not all(_no_overlap(v) for v in component_intervals.values()):
                        continue
                    score = (n_selected, sum(options[i]["energy"] for i in subset),
                             max(options[i]["resource_end"] for i in subset))
                    if best is None or score < best:
                        best = score
        if best is not None:
            return {"solver_status": "OPTIMAL", "sortie_count": best[0],
                    "energy_kwh": best[1], "completion_s": best[2]}
    return {"solver_status": "INFEASIBLE", "sortie_count": None,
            "energy_kwh": None, "completion_s": None}


def run_small_exact_tests():
    """Four complete physics/resource schedule regression instances.

    The examples are intentionally small enough to enumerate every selected
    option and every UAV/component assignment; no heuristic result appears in
    this oracle.
    """
    cases = {
        "B-Small-1": {
            "demands": {"D1", "D2"}, "n_relays": 1, "n_components": 1,
            "options": [
                {"covers": {"D1"}, "launch": 0, "resource_end": 240, "charge_end": 400, "energy": 1.0},
                {"covers": {"D2"}, "launch": 420, "resource_end": 660, "charge_end": 820, "energy": 1.2},
            ], "expected": ("OPTIMAL", 2),
        },
        "B-Small-2": {
            "demands": {"D1[100,200]", "D2[130,180]"}, "n_relays": 1, "n_components": 1,
            "options": [
                {"covers": {"D1[100,200]", "D2[130,180]"}, "launch": 0, "resource_end": 260, "charge_end": 400, "energy": 1.1},
                {"covers": {"D1[100,200]"}, "launch": 0, "resource_end": 260, "charge_end": 400, "energy": 0.7},
                {"covers": {"D2[130,180]"}, "launch": 30, "resource_end": 240, "charge_end": 390, "energy": 0.6},
            ], "expected": ("OPTIMAL", 1),
        },
        "B-Small-3": {
            "demands": {"D1", "D2"}, "n_relays": 1, "n_components": 2,
            "options": [
                {"covers": {"D1"}, "launch": 0, "resource_end": 300, "charge_end": 380, "energy": 0.8},
                {"covers": {"D2"}, "launch": 50, "resource_end": 350, "charge_end": 430, "energy": 0.8},
            ], "expected": ("INFEASIBLE", None),
        },
        "B-Small-4": {
            "demands": {"D1", "D2"}, "n_relays": 2, "n_components": 1,
            "options": [
                {"covers": {"D1"}, "launch": 0, "resource_end": 220, "charge_end": 600, "energy": 0.9},
                {"covers": {"D2"}, "launch": 250, "resource_end": 470, "charge_end": 850, "energy": 0.9},
            ], "expected": ("INFEASIBLE", None),
        },
    }
    output = {}
    for case_id, case in cases.items():
        answer = _enumerate_exact(case["demands"], case["options"], n_relays=case["n_relays"],
                                  n_components=case["n_components"])
        expected_status, expected_count = case["expected"]
        output[case_id] = {**answer, "expected_status": expected_status,
                           "expected_sortie_count": expected_count,
                           "pass": answer["solver_status"] == expected_status and
                           answer["sortie_count"] == expected_count}
    return output


def validate_q3_b(result, *, inputs=None, dem=None, transport_state=None, transport_schedule=None):
    """Recompute all Q3-B gates from result data, not ``result.checks``."""
    inputs = inputs or load_q3_inputs()
    dem = dem or get_dem()
    candidates = {str(c["candidate_id"]): c for c in result.candidates}
    coverability: dict[str, int] = {}
    candidate_cover_sets = {candidate_id: set() for candidate_id in candidates}
    for demand in result.demands:
        count = 0
        for candidate_id, candidate in candidates.items():
            if strict_replay_coverage(demand, candidate, inputs=inputs, dem=dem):
                count += 1
                candidate_cover_sets[candidate_id].add(str(demand.demand_id))
        coverability[str(demand.demand_id)] = count
    selected_by_demand = {str(d.demand_id): [] for d in result.demands}
    for sortie in result.sorties:
        for demand_id in sortie.demand_ids:
            selected_by_demand.setdefault(str(demand_id), []).append(sortie)
    scheduled = {}
    per_demand_replay = {}
    for demand in result.demands:
        demand_id = str(demand.demand_id)
        assigned = selected_by_demand.get(demand_id, [])
        scheduled[demand_id] = any(
            sortie.service_start_s <= demand.start_s + 1e-7 and sortie.service_end_s >= demand.end_s - 1e-7 and
            strict_replay_coverage(demand, candidates[sortie.candidate_id], inputs=inputs, dem=dem)
            for sortie in assigned)
        replay = evaluate_transport_communication(demand.trajectory_samples, comm=inputs["communication"],
                                                  nodes=inputs["nodes"], dem=dem, dt_s=2.0,
                                                  relay_services=result.relay_services)
        per_demand_replay[demand_id] = bool(replay.communication_feasible and replay.outage_samples == 0)
    relay_intervals = {}
    component_intervals = {}
    for sortie in result.sorties:
        relay_intervals.setdefault(sortie.relay_id, []).append((sortie.launch_start_s, sortie.resource_end_s))
        component_intervals.setdefault(sortie.energy_component_id, []).append((sortie.launch_start_s, sortie.charge_end_s))
    all_coverable = all(count > 0 for count in coverability.values())
    all_scheduled = all(scheduled.values())
    full_replay = _replay_transport(inputs, transport_state, transport_schedule, result.relay_services,
                                    dt_s=2.0, dem=dem)
    all_replayed = all(per_demand_replay.values()) and bool(full_replay) and all(
        row.get("communication_feasible", False) and row.get("outage_samples", 1) == 0 for row in full_replay)
    small_exact = run_small_exact_tests()
    pruning_by_candidate = {str(row.get("candidate_id")): row for row in result.pruning_audit}
    complete_option_space = bool(result.option_space_complete) and len(pruning_by_candidate) == len(candidates) and all(
        int(pruning_by_candidate[candidate_id].get("total_contiguous_windows", -1)) ==
        len(candidate_cover_sets[candidate_id]) * (len(candidate_cover_sets[candidate_id]) + 1) // 2 and
        int(pruning_by_candidate[candidate_id].get("physics_feasible_options", -1)) +
        int(pruning_by_candidate[candidate_id].get("physics_rejected_options", -1)) ==
        int(pruning_by_candidate[candidate_id].get("total_contiguous_windows", -2))
        for candidate_id in candidates)
    baseline_feasible = result.baseline_status == "FEASIBLE"
    baseline_proven_infeasible = result.baseline_status == "INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET"
    status_mapping_pass = (
        (result.solver_status in {"OPTIMAL", "FEASIBLE"} and
         ((baseline_feasible and all_replayed and all_scheduled) or result.baseline_status == "UNRESOLVED")) or
        (result.solver_status == "INFEASIBLE" and complete_option_space and baseline_proven_infeasible) or
        (result.solver_status in {"UNKNOWN", "NOT_AVAILABLE"} and result.baseline_status == "UNRESOLVED"))
    checks = {
        "all_demands_candidate_coverable": all_coverable,
        "all_demands_scheduled_covered": all_scheduled,
        "relay_uav_overlap_zero": all(_no_overlap(v) for v in relay_intervals.values()),
        "energy_component_overlap_zero": all(_no_overlap(v) for v in component_intervals.values()),
        "charging_pass": all(s.charge_end_s >= s.resource_end_s - 1e-7 for s in result.sorties),
        "arrival_timing_pass": all(s.relay_ready_s <= s.service_start_s + 1e-7 for s in result.sorties),
        "reserve_pass": all(s.soc_after >= float(inputs["relay_type"]["reserve_rho"]) - 1e-9 for s in result.sorties),
        "full_trajectory_communication_feasible": all_replayed,
        "exact_validation_pass": all(row["pass"] for row in small_exact.values()),
        "service_option_space_complete": complete_option_space,
        "status_mapping_pass": status_mapping_pass,
    }
    audit = [{"demand_id": did, "candidate_coverable": coverability[did] > 0,
              "n_covering_candidates": coverability[did], "scheduled_covered": scheduled[did],
              "selected_sortie_id": ";".join(s.sortie_id for s in selected_by_demand[did]) or None,
              "full_replay_covered": per_demand_replay[did]} for did in coverability]
    decoder_checks = {key: checks[key] for key in ("all_demands_candidate_coverable", "exact_validation_pass",
                                                    "service_option_space_complete", "status_mapping_pass")}
    decoder_validation_status = "PASS" if all(decoder_checks.values()) else "FAIL"
    return {"status": decoder_validation_status,
            "decoder_validation_status": decoder_validation_status,
            "decoder_checks": decoder_checks,
            "checks": checks, "coverage_audit": audit, "small_exact": small_exact,
            "metrics": result.metrics, "reason": result.reason,
            "full_replay_audit": full_replay,
            "decoder_status": result.decoder_status, "baseline_status": result.baseline_status,
            "solver_status": result.solver_status}


def validate_baseline():
    result = decode_relay_schedule(dt_s=2.0)
    return result, validate_q3_b(result)


if __name__ == "__main__":
    import json
    result, validation = validate_baseline()
    print(json.dumps({"result": result.as_dict(), "validation": validation}, ensure_ascii=False, indent=2))
