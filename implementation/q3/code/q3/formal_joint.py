"""C1 formal Q3-C evaluation path: transport audit -> real Q3-B decoder -> validator."""
from __future__ import annotations

from typing import Any, Mapping

from .joint_cache import JointCache, canonical_signature
from .joint_models import JointEvaluation
from .joint_objective import joint_metrics
from .joint_validator import validate_joint_candidate
from .transport_adapter import decode_transport_candidate, relay_decoder_contract, transport_signature


def _field(value, key, default=None):
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def evaluate_joint_candidate(*, decoder, transport_state, transport_schedule,
                             transport_validation: Mapping[str, Any], transport_metrics: Mapping[str, Any],
                             cache: JointCache | None = None, candidate_spacing_m: float = 1500.0,
                             dt_s: float = 2.0, uav_signature=None, battery_signature=None,
                             stop_sequence=None, trip_grouping=None) -> JointEvaluation:
    """Evaluate one transport candidate with the actual Q3-B decoder.

    The relay schedule is deliberately not stored in Q3State.  It is a derived
    result and is re-decoded whenever a transport signature or spacing changes.
    """
    if transport_validation.get("status") not in {"PASS", "FEASIBLE"}:
        return JointEvaluation(False, reason="transport_hard_validation_failed",
                               checks={"transport_hard_validation": False})
    route_signature = {"transport_state": transport_state, "transport_schedule": transport_schedule,
                       "stop_sequence": stop_sequence, "trip_grouping": trip_grouping}
    relay_result = None
    if cache is not None:
        relay_result = cache.get_schedule(route_signature, 0.0, uav_signature, battery_signature,
                                          stop_sequence=stop_sequence, trip_grouping=trip_grouping,
                                          candidate_spacing_m=candidate_spacing_m)
    if relay_result is None:
        relay_result = decoder.decode_relay_schedule(transport_state, transport_schedule, dt_s=dt_s,
                                                     candidate_spacing_m=candidate_spacing_m)
        if cache is not None:
            cache.put_schedule(route_signature, 0.0, uav_signature, battery_signature, relay_result,
                               stop_sequence=stop_sequence, trip_grouping=trip_grouping,
                               candidate_spacing_m=candidate_spacing_m)
    validation = validate_joint_candidate(transport_validation, relay_result)
    if validation["status"] != "PASS":
        return JointEvaluation(False, reason=validation["reason"], checks=validation["checks"])
    relay_metrics = _field(relay_result, "metrics", {}) or {}
    metrics = joint_metrics(transport_metrics, relay_metrics)
    return JointEvaluation(True, metrics=metrics, checks=validation["checks"])


def evaluate_q3_transport_state(*, decoder, transport_state, cache: JointCache | None = None,
                                candidate_spacing_m: float = 1500.0, seed: int = 0,
                                transport_time_limit_s: float = 60.0) -> JointEvaluation:
    """The formal state chain used by C2+: Q2 decode -> Q2 replay -> real Q3-B."""
    schedule, transport_validation = decode_transport_candidate(
        transport_state, cp_workers=1, time_limit_s=transport_time_limit_s, seed=seed)
    if transport_validation.get("status") not in {"PASS", "FEASIBLE"} or schedule.status not in {"PASS", "FEASIBLE"}:
        return JointEvaluation(False, reason="transport_hard_validation_failed",
                               checks={"transport_hard_validation": False})
    if cache is not None:
        signature = transport_signature(transport_state, schedule)
        cache.put_geometry(signature, {"transport_validation": transport_validation})
    relay_state, relay_schedule = relay_decoder_contract(transport_state, schedule)
    return evaluate_joint_candidate(
        decoder=decoder, transport_state=relay_state, transport_schedule=relay_schedule,
        transport_validation=transport_validation, transport_metrics=transport_validation.get("metrics", {}),
        cache=cache, candidate_spacing_m=candidate_spacing_m, uav_signature=tuple(a.uid for a in schedule.assignments),
        battery_signature=tuple(a.battery_id for a in schedule.assignments),
        stop_sequence=tuple(tuple(t.stop_sequence) for t in transport_state.trips),
        trip_grouping=tuple(tuple(t.box_ids) for t in transport_state.trips))


def formal_decoder_identity(decoder) -> str:
    return canonical_signature({"module": decoder.decoder_function.__module__,
                                "qualname": decoder.decoder_function.__qualname__})
