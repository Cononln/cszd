"""Framework-only Q3-C tests. They never invoke a formal optimizer."""
from __future__ import annotations

from .joint_cache import JointCache
from .joint_models import JointMetrics
from .joint_objective import FixedNormalization, joint_metrics
from .joint_operators import preserves_box_uniqueness
from .joint_validator import validate_q3_joint
from .relay_decoder_protocol import RelayDecoderStub


def run_framework_tests():
    transport = {"WTD": 2.0, "Cmax_s": 100.0, "total_energy_kwh": 3.0, "n_trips": 2}
    relay = {"relay_cmax_s": 120.0, "relay_energy_kwh": 1.5, "relay_sortie_count": 1}
    metrics = joint_metrics(transport, relay)
    cache = JointCache()
    cache.put_schedule(("route",), 0.0, ("U01",), ("B01",), "a")
    tests = {
        "joint_cmax_arithmetic": metrics.joint_Cmax_s == 120.0,
        "joint_energy_arithmetic": metrics.total_energy_kwh == 4.5,
        "transport_infeasible_short_circuit": validate_q3_joint({"status": "INFEASIBLE"}, {"status": "PASS"})["status"] == "INFEASIBLE",
        "relay_infeasible_short_circuit": validate_q3_joint({"status": "PASS"}, {"status": "INFEASIBLE"})["status"] == "INFEASIBLE",
        "cache_distinguishes_start_time": cache.get_schedule(("route",), 1.0, ("U01",), ("B01",)) is None,
        "cache_retrieves_same_signature": cache.get_schedule(("route",), 0.0, ("U01",), ("B01",)) == "a",
        "stub_only_test_protocol": RelayDecoderStub().decode_relay_schedule(None, None)["checks"]["stub"],
        "fixed_normalization": FixedNormalization({k: 0.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")},
                                                    {k: 1.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")}).tchebycheff(
                                                        {"WTD": 0.0, "joint_Cmax_s": 0.0, "total_energy_kwh": 0.0, "transport_n_trips": 0.0, "relay_n_sorties": 0.0},
                                                        {k: 1.0 for k in ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")}) == 0.0,
    }
    return {"status": "PASS" if all(tests.values()) else "FAIL", "tests": tests,
            "formal_optimization_entered": False, "real_decoder_connected": False}


if __name__ == "__main__":
    import json
    print(json.dumps(run_framework_tests(), ensure_ascii=False, indent=2))
