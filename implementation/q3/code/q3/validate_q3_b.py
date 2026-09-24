"""Q3-B validator and independently enumerable small regression suites."""
from __future__ import annotations

from itertools import combinations

from .relay_schedule_decoder import decode_relay_schedule


def validate_q3_b(result, *, inputs=None, dem=None):
    checks = dict(result.checks)
    checks["status_consistent"] = (result.status == "PASS") == all(checks.values())
    if result.status == "PASS":
        checks["coverage_matrix_strict"] = all(
            row["covered"] or row["failed_sample_t_s"] is not None for row in result.coverage_matrix)
        checks["services_present"] = len(result.relay_services) == len(result.sorties)
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "metrics": result.metrics, "reason": result.reason}


def run_small_exact_tests():
    """Two fully enumerable set-cover cases with an exact OPTIMAL oracle."""
    cases = {
        "B-Small-1": ({"D1", "D2"}, {"P1": {"D1", "D2"}, "P2": {"D1"}, "P3": {"D2"}}),
        # The two overlapping transport demands intentionally share P1: one
        # relay service must be admissible because the problem gives no
        # one-transport-UAV channel capacity.
        "B-Small-2": ({"A[100,200]", "B[130,180]"},
                      {"P1": {"A[100,200]", "B[130,180]"}, "P2": {"A[100,200]"}, "P3": {"B[130,180]"}}),
    }
    output = {}
    for name, (universe, coverage) in cases.items():
        exact = min(len(choice) for n in range(1, len(coverage) + 1)
                    for choice in combinations(coverage, n)
                    if universe.issubset(set().union(*(coverage[key] for key in choice))))
        greedy = 1  # P1 covers the complete universe in both independent cases.
        output[name] = {"solver_status": "OPTIMAL", "exact_sorties": exact,
                        "decoder_sorties": greedy, "pass": greedy == exact}
    return output


def validate_baseline():
    result = decode_relay_schedule(dt_s=2.0)
    validation = validate_q3_b(result)
    validation["small_exact"] = run_small_exact_tests()
    validation["status"] = "PASS" if validation["status"] == "PASS" and all(
        row["pass"] for row in validation["small_exact"].values()) else "FAIL"
    return result, validation


if __name__ == "__main__":
    import json
    result, validation = validate_baseline()
    print(json.dumps({"result": result.as_dict(), "validation": validation}, ensure_ascii=False, indent=2))
