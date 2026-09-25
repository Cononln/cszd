"""C2 candidate generation, temporal repair and real Q3-B evaluation."""
from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from time import perf_counter
from typing import Any, Mapping

from .transport_adapter import (decode_transport_candidate, load_q2_formal_state,
                                relay_decoder_contract)
from q2.models import Q2State
from q2.validate_q2 import validate_solution

from .c2_start_time_repair import repair_start_times, schedule_to_dict
from .joint_validator import validate_joint_candidate
from .relay_decoder_protocol import Q3BRelayDecoderAdapter
from .validate_q3_b import validate_q3_b


# These are the eight deterministic single-type variants ranked by the
# preceding C2-A surrogate screen.  The route evaluator still decides whether
# each candidate is physically admissible at runtime.
SINGLE_TYPE_VARIANTS: tuple[tuple[int, str], ...] = (
    (23, "B"), (9, "B"), (15, "C"), (9, "C"),
    (14, "C"), (16, "C"), (5, "C"), (3, "C"),
)

COMBINATION_VARIANTS: tuple[tuple[tuple[int, str], ...], ...] = (
    ((23, "B"), (9, "B")),
    ((15, "C"), (16, "C")),
    ((23, "B"), (16, "C")),
    ((9, "B"), (15, "C")),
)


def canonical_transport_payload(state: Q2State | Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete, scheduler-relevant transport decision payload.

    The payload deliberately excludes candidate names, run time and validation
    products.  It includes the stable trip order because Q2 decodes that order
    into resource assignments, and preserves every actual route/load decision.
    Box order within a stop and unassigned-box order are canonicalised because
    neither changes the Q2 decoding problem.
    """
    if isinstance(state, Q2State):
        raw_trips = state.trips
        unassigned = state.unassigned
    else:
        raw_trips = state.get("trips", [])
        unassigned = state.get("unassigned", [])
    trips = []
    for order, trip in enumerate(raw_trips, 1):
        if isinstance(trip, Mapping):
            gtype = trip.get("gtype")
            stops = trip.get("stop_sequence", [])
            boxes = trip.get("boxes_by_stop", {})
        else:
            gtype = trip.gtype
            stops = trip.stop_sequence
            boxes = trip.boxes_by_stop
        stop_sequence = [str(stop) for stop in stops]
        trips.append({
            "trip_order": order,
            "gtype": str(gtype),
            "stop_sequence": stop_sequence,
            "boxes_by_stop": {
                stop: sorted(str(box) for box in boxes.get(stop, []))
                for stop in stop_sequence
            },
        })
    return {
        "trip_count": len(trips),
        "trips": trips,
        "unassigned": sorted(str(box) for box in unassigned),
    }


def canonical_transport_signature(state: Q2State | Mapping[str, Any]) -> str:
    """Stable SHA-256 identity for one transport decision state."""
    encoded = json.dumps(canonical_transport_payload(state), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _transport_state_payload(state: Q2State) -> dict[str, Any]:
    """Persist the same state fields used for the canonical signature."""
    return {
        "trips": [
            {"gtype": trip.gtype, "stop_sequence": list(trip.stop_sequence),
             "boxes_by_stop": {stop: list(boxes) for stop, boxes in trip.boxes_by_stop.items()}}
            for trip in state.trips
        ],
        "unassigned": list(state.unassigned),
    }


def _result_summary(result) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "decoder_status": result.decoder_status,
        "baseline_status": result.baseline_status,
        "solver_status": result.solver_status,
        "reason": result.reason,
        "candidate_spacing_m": result.candidate_spacing_m,
        "metrics": dict(result.metrics),
        "checks": dict(result.checks),
        "coverage_audit": list(result.coverage_audit),
        "resource_audit": list(result.resource_audit),
        "relay_sorties": [s.as_dict() for s in result.sorties],
        "relay_services": list(result.relay_services),
        "replay_audit": list(result.replay_audit),
    }


def _violations(validation: dict[str, Any] | None, relay, joint: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "transport": [] if not validation else [key for key, value in validation.get("checks", {}).items() if not value],
        "relay": [] if relay is None else [key for key, value in relay.checks.items() if not value],
        "joint": [] if joint is None else [key for key, value in joint.get("checks", {}).items() if not value],
    }


def _candidate_state(base: Q2State, trip_number: int | None = None, gtype: str | None = None) -> Q2State:
    if trip_number is None:
        return base
    index = int(trip_number) - 1
    trips = list(base.trips)
    trips[index] = replace(trips[index], gtype=str(gtype))
    return Q2State(tuple(trips), base.unassigned)


def evaluate_c2a_candidate(candidate_id: str, parent_id: str, state: Q2State,
                           *, operator: str) -> dict[str, Any]:
    started = perf_counter()
    baseline_schedule, baseline_transport = decode_transport_candidate(
        state, cp_workers=1, time_limit_s=60.0, seed=0)
    baseline_q2 = validate_solution(state, baseline_schedule)
    baseline_relay = baseline_joint = baseline_relay_validation = None
    if baseline_schedule.status in {"PASS", "FEASIBLE"} and baseline_transport.get("status") in {"PASS", "FEASIBLE"}:
        relay_state, relay_schedule = relay_decoder_contract(state, baseline_schedule)
        baseline_relay = Q3BRelayDecoderAdapter().decode_relay_schedule(
            relay_state, relay_schedule, candidate_spacing_m=1500.0)
        baseline_relay_validation = validate_q3_b(
            baseline_relay, transport_state=relay_state, transport_schedule=relay_schedule)
        baseline_joint = validate_joint_candidate(baseline_transport, baseline_relay)
    repaired_schedule, repair_audit = repair_start_times(state, baseline_schedule)
    repaired_transport = validate_solution(state, repaired_schedule)
    repaired_relay = repaired_joint = repaired_relay_validation = None
    if repaired_schedule.status in {"PASS", "FEASIBLE"} and repaired_transport.get("status") in {"PASS", "FEASIBLE"}:
        relay_state, relay_schedule = relay_decoder_contract(state, repaired_schedule)
        repaired_relay = Q3BRelayDecoderAdapter().decode_relay_schedule(
            relay_state, relay_schedule, candidate_spacing_m=1500.0)
        repaired_relay_validation = validate_q3_b(
            repaired_relay, transport_state=relay_state, transport_schedule=relay_schedule)
        repaired_joint = validate_joint_candidate(repaired_transport, repaired_relay)
    feasible = bool(repaired_joint and repaired_joint.get("status") == "PASS" and
                    repaired_relay_validation and
                    repaired_relay_validation.get("decoder_validation_status") == "PASS" and
                    all(repaired_relay_validation.get("checks", {}).values()))
    return {
        "candidate_id": candidate_id,
        "parent_id": parent_id,
        "repair_stage": "C2-A",
        "operator": operator,
        "state_signature": canonical_transport_signature(state),
        "transport_state": _transport_state_payload(state),
        "baseline": {"schedule": schedule_to_dict(baseline_schedule),
                      "transport_validation": baseline_q2,
                      "relay": _result_summary(baseline_relay),
                      "relay_validation": baseline_relay_validation,
                      "joint": baseline_joint,
                      "violations": _violations(baseline_q2, baseline_relay, baseline_joint)},
        "repair": repair_audit.as_dict(),
        "repaired": {"schedule": schedule_to_dict(repaired_schedule),
                      "transport_validation": repaired_transport,
                      "relay": _result_summary(repaired_relay),
                      "relay_validation": repaired_relay_validation,
                      "joint": repaired_joint,
                      "violations": _violations(repaired_transport, repaired_relay, repaired_joint)},
        "joint_status": "PASS" if feasible else (repaired_joint or {}).get("status", "UNRESOLVED"),
        "feasible_seed_found": feasible,
        "runtime_s": perf_counter() - started,
    }


def run_c2a() -> dict[str, Any]:
    base = load_q2_formal_state()
    raw_descriptors = [("C2A-BASE", "Q2-FORMAL", base, "baseline_wave_repair")]
    for trip_number, gtype in SINGLE_TYPE_VARIANTS:
        raw_descriptors.append((f"C2A-SINGLE-T{trip_number:03d}-{gtype}", "Q2-FORMAL",
                                _candidate_state(base, trip_number, gtype),
                                f"single_type_adjustment_T{trip_number:03d}_{gtype}"))
    noop_removed = 0
    duplicate_removed = 0
    candidates = []
    seen_signatures: set[str] = set()
    for descriptor in raw_descriptors:
        candidate_id, parent_id, state, operator = descriptor
        if candidate_id != "C2A-BASE":
            trip_number = int(candidate_id.split("-T", 1)[1].split("-", 1)[0])
            proposed = candidate_id.rsplit("-", 1)[1]
            if base.trips[trip_number - 1].gtype == proposed:
                noop_removed += 1
                continue
        signature = canonical_transport_signature(state)
        if signature in seen_signatures:
            duplicate_removed += 1
            continue
        seen_signatures.add(signature)
        candidates.append(descriptor)
    # Q3-B's solver is the expensive independent unit.  Evaluate the bounded
    # C2-A neighborhood concurrently while retaining deterministic output order.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="q3-c2a") as pool:
        futures = [pool.submit(evaluate_c2a_candidate, candidate[0], candidate[1],
                                candidate[2], operator=candidate[3])
                   for candidate in candidates]
        results = [future.result() for future in futures]
    feasible = [row for row in results if row["feasible_seed_found"]]
    return {
        "phase": "Q3-C-C2-A", "status": "PASS" if feasible else "UNRESOLVED",
        "generated_raw_count": len(raw_descriptors),
        "noop_removed_count": noop_removed,
        "duplicate_removed_count": duplicate_removed,
        "unique_candidate_count": len(results),
        "candidate_count": len(results), "transport_feasible_count": sum(
            row["repaired"]["transport_validation"].get("status") == "PASS" for row in results),
        "relay_evaluated_count": sum(bool(row["repaired"]["relay"]) for row in results),
        "joint_feasible_count": len(feasible),
        "candidates": results,
        "feasible_candidates": [row["candidate_id"] for row in feasible],
    }


def run_c2b() -> dict[str, Any]:
    """Evaluate a bounded, predeclared combination neighborhood only."""
    base = load_q2_formal_state()
    raw_descriptors = []
    noop_removed = 0
    duplicate_removed = 0
    base_signature = canonical_transport_signature(base)
    c2a_signatures = {base_signature}
    for trip_number, gtype in SINGLE_TYPE_VARIANTS:
        if base.trips[trip_number - 1].gtype == gtype:
            continue
        c2a_signatures.add(canonical_transport_signature(_candidate_state(base, trip_number, gtype)))
    descriptors = []
    seen_signatures = set(c2a_signatures)
    for number, changes in enumerate(COMBINATION_VARIANTS, 1):
        state = base
        labels = []
        is_noop = False
        for trip_number, gtype in changes:
            if base.trips[trip_number - 1].gtype == gtype:
                is_noop = True
                break
            state = _candidate_state(state, trip_number, gtype)
            labels.append(f"T{trip_number:03d}-{gtype}")
        raw_descriptors.append((f"C2B-COMB-{number:02d}", "Q2-FORMAL", state,
                                "combination_" + "+".join(labels), is_noop))
    for candidate_id, parent_id, state, operator, is_noop in raw_descriptors:
        if is_noop:
            noop_removed += 1
            continue
        signature = canonical_transport_signature(state)
        if signature in seen_signatures:
            duplicate_removed += 1
            continue
        seen_signatures.add(signature)
        descriptors.append((candidate_id, parent_id, state, operator))
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="q3-c2b") as pool:
        futures = [pool.submit(evaluate_c2a_candidate, desc[0], desc[1], desc[2], operator=desc[3])
                   for desc in descriptors]
        results = [future.result() for future in futures]
    for row in results:
        row["repair_stage"] = "C2-B"
    feasible = [row for row in results if row["feasible_seed_found"]]
    return {"phase": "Q3-C-C2-B", "status": "PASS" if feasible else "UNRESOLVED",
            "generated_raw_count": len(raw_descriptors),
            "noop_removed_count": noop_removed,
            "duplicate_removed_count": duplicate_removed,
            "unique_candidate_count": len(results),
            "candidate_count": len(results), "transport_feasible_count": sum(
                row["repaired"]["transport_validation"].get("status") == "PASS" for row in results),
            "relay_evaluated_count": sum(bool(row["repaired"]["relay"]) for row in results),
            "joint_feasible_count": len(feasible), "candidates": results,
            "feasible_candidates": [row["candidate_id"] for row in feasible]}
