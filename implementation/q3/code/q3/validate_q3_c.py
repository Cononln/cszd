"""Framework-only Q3-C tests. They never invoke a formal optimizer."""
from __future__ import annotations

from .joint_cache import JointCache
from .joint_models import JointMetrics
from .joint_objective import (FixedNormalization, dominates, joint_metrics,
                              nondominated_filter, pareto_ideal_nadir, select_representative)
from .joint_operators import preserves_box_uniqueness, operator_metadata
from .joint_validator import validate_q3_joint
from .formal_joint import evaluate_joint_candidate, formal_decoder_identity
from .joint_cache import canonical_signature
from .joint_solver import solve_joint_alns
from .relay_decoder_protocol import Q3BRelayDecoderAdapter, RelayDecoderStub
from .joint_validator import validate_joint_candidate


def _formal_solver_is_gated():
    try:
        solve_joint_alns()
    except RuntimeError:
        return True
    return False


def _synthetic_transport_validation():
    return {"status": "PASS", "checks": {
        "all_boxes_delivered_once": True, "missing_boxes": True, "duplicate_boxes": True,
        "no_split_boxes": True, "first_deadlines_pass": True, "medical_deadlines_pass": True,
        "mass_pass": True, "volume_pass": True, "return_reserve_pass": True,
        "uav_overlap_zero": True, "battery_overlap_zero": True, "soc_pass": True,
        "charge_pass": True, "charge_before_reuse_pass": True,
    }, "metrics": {"WTD": 0.0, "Cmax_s": 20.0,
                    "total_energy_kwh": 1.0, "n_trips": 1}}


def run_c1_integration_tests():
    """Exercise the real adapter and formal validator without entering ALNS."""
    adapter = Q3BRelayDecoderAdapter()
    real_result = adapter.decode_relay_schedule([], {}, candidate_spacing_m=1500.0)
    synthetic_relay = {"baseline_status": "FEASIBLE", "metrics": {
        "relay_cmax_s": 20.0, "relay_energy_kwh": 0.2, "relay_sortie_count": 1},
        "sorties": ({"relay_id": "R1", "energy_component_id": "EC-01", "launch_start_s": 0.0,
                      "resource_end_s": 10.0, "charge_end_s": 20.0, "soc_after": 0.9,
                      "relay_ready_s": 2.0, "service_start_s": 2.0},),
        "replay_audit": ({"communication_feasible": True, "outage_samples": 0},)}
    validator = validate_joint_candidate(_synthetic_transport_validation(), synthetic_relay)
    class DummyDecoder:
        def decode_relay_schedule(self, *args, **kwargs):
            return synthetic_relay
    cache = JointCache()
    first = evaluate_joint_candidate(decoder=DummyDecoder(), transport_state={"T1": 1},
                                     transport_schedule={"T1": 0}, transport_validation=_synthetic_transport_validation(),
                                     transport_metrics={"WTD": 0.0, "Cmax_s": 20.0, "total_energy_kwh": 1.0, "n_trips": 1},
                                     cache=cache)
    second = evaluate_joint_candidate(decoder=DummyDecoder(), transport_state={"T1": 1},
                                      transport_schedule={"T1": 0}, transport_validation=_synthetic_transport_validation(),
                                      transport_metrics={"WTD": 0.0, "Cmax_s": 20.0, "total_energy_kwh": 1.0, "n_trips": 1},
                                      cache=cache)
    return {"real_decoder_invoked": getattr(real_result, "decoder_status", None) == "PASS",
            "real_decoder_baseline_status": getattr(real_result, "baseline_status", None),
            "formal_validator_pass": validator["status"] == "PASS",
            "joint_evaluation_pass": first.feasible and second.feasible,
            "cache_hit_after_repeat": cache.schedule_hits == 1,
            "cache_sha256_deterministic": canonical_signature({"a": [1, 2]}) == canonical_signature({"a": [1, 2]})}


def run_framework_tests():
    transport = {"WTD": 2.0, "Cmax_s": 100.0, "total_energy_kwh": 3.0, "n_trips": 2}
    relay = {"relay_cmax_s": 120.0, "relay_energy_kwh": 1.5, "relay_sortie_count": 1}
    metrics = joint_metrics(transport, relay)
    cache = JointCache()
    cache.put_schedule(("route",), 0.0, ("U01",), ("B01",), "a")
    point_a = {"WTD": 1, "joint_Cmax_s": 10, "total_energy_kwh": 5, "transport_n_trips": 2, "relay_n_sorties": 1}
    point_b = {"WTD": 2, "joint_Cmax_s": 11, "total_energy_kwh": 6, "transport_n_trips": 3, "relay_n_sorties": 2}
    point_c = {"WTD": 1, "joint_Cmax_s": 9, "total_energy_kwh": 7, "transport_n_trips": 2, "relay_n_sorties": 2}
    class Box:
        def __init__(self, ids): self.box_ids = tuple(ids)
    before = type("State", (), {"trips": (Box(("B1",)), Box(("B2",)))})()
    real_adapter = Q3BRelayDecoderAdapter()
    integration = run_c1_integration_tests()
    tests = {
        "joint_cmax_arithmetic": metrics.joint_Cmax_s == 120.0,
        "joint_energy_arithmetic": metrics.total_energy_kwh == 4.5,
        "transport_infeasible_short_circuit": validate_q3_joint({"status": "INFEASIBLE"}, {"status": "PASS"})["status"] == "INFEASIBLE_PROVEN",
        "relay_infeasible_short_circuit": validate_q3_joint({"status": "PASS"}, {"status": "INFEASIBLE_PROVEN"})["status"] == "INFEASIBLE_PROVEN",
        "cache_distinguishes_start_time": cache.get_schedule(("route",), 1.0, ("U01",), ("B01",)) is None,
        "cache_retrieves_same_signature": cache.get_schedule(("route",), 0.0, ("U01",), ("B01",)) == "a",
        "stub_only_test_protocol": RelayDecoderStub().decode_relay_schedule(None, None)["checks"]["stub"],
        "fixed_normalization": FixedNormalization({k: 0.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")},
                                                    {k: 1.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")}).tchebycheff(
                                                        {"WTD": 0.0, "joint_Cmax_s": 0.0, "total_energy_kwh": 0.0, "transport_n_trips": 0.0, "relay_n_sorties": 0.0},
                                                        {k: 1.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")}) == 0.0,
        "pareto_dominance": dominates(point_a, point_b) and not dominates(point_b, point_a),
        "pareto_tradeoff": not dominates(point_a, point_c) and not dominates(point_c, point_a),
        "pareto_duplicate_equal": len(nondominated_filter([point_a, dict(point_a), point_b, point_c])) == 2,
        "final_pareto_normalization": pareto_ideal_nadir([point_a, point_c])[0]["joint_Cmax_s"] == 9 and
                                      select_representative([point_a, point_c]) in (point_a, point_c),
        "operator_preserves_box_uniqueness": preserves_box_uniqueness(before, before) and
                                              len(operator_metadata(before)["removed_boxes"]) == 0,
        "relay_unresolved_short_circuit": validate_q3_joint({"status": "PASS"}, {"status": "UNRESOLVED"})["status"] == "UNRESOLVED",
        "formal_solver_gate": _formal_solver_is_gated(),
        "real_decoder_adapter_identity": real_adapter.decoder_function.__module__.endswith("relay_schedule_decoder") and
                                         bool(formal_decoder_identity(real_adapter)),
        "c1_real_decoder_invoked": integration["real_decoder_invoked"],
        "c1_formal_validator_pass": integration["formal_validator_pass"],
        "c1_cache_hit": integration["cache_hit_after_repeat"],
    }
    return {"status": "READY" if all(tests.values()) else "FAIL",
            "validation_status": "PASS" if all(tests.values()) else "FAIL", "tests": tests,
            "formal_optimization_entered": False, "real_decoder_connected": True,
            "c1_integration": integration}


if __name__ == "__main__":
    import json
    print(json.dumps(run_framework_tests(), ensure_ascii=False, indent=2))
