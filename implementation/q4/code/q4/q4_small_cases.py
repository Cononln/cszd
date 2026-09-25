"""Deterministic small cases for the Q4 partition model and validator."""
from __future__ import annotations

import json
from typing import Any

from .q3_adapter import results_root
from .q4_model import evaluate_partition, prepare_state
from .validate_q4 import validate_candidate


def run_small_cases() -> dict[str, Any]:
    prepared = prepare_state()
    n = len(prepared["components"])
    cases: list[dict[str, Any]] = []
    feasible_2 = (tuple(range(n - 1)), (n - 1,))
    first = evaluate_partition(prepared, feasible_2, candidate_id="Q4-SMALL-1", parent_id="C2A-BASE", operator="small_feasible")
    cases.append({"case_id": "Q4-Small-1 feasible", "expected": "PASS", "actual": validate_candidate(first, prepared)["status"],
                  "purpose": "two nonempty legal groups preserve every multi-stop component"})
    feasible_3 = (tuple(range(n - 2)), (n - 2,), (n - 1,))
    second = evaluate_partition(prepared, feasible_3, candidate_id="Q4-SMALL-2", parent_id="C2A-BASE", operator="small_boundary")
    cases.append({"case_id": "Q4-Small-2 boundary feasible", "expected": "PASS", "actual": validate_candidate(second, prepared)["status"],
                  "purpose": "three-group boundary case with singleton components"})
    infeasible = (tuple(range(n - 1)), (n - 1,), tuple())
    third = evaluate_partition(prepared, infeasible, candidate_id="Q4-SMALL-3", parent_id="C2A-BASE", operator="small_infeasible")
    cases.append({"case_id": "Q4-Small-3 infeasible", "expected": "FAIL", "actual": validate_candidate(third, prepared)["status"],
                  "purpose": "empty task group violates the nonempty-group constraint"})
    fourth = evaluate_partition(prepared, feasible_2, candidate_id="Q4-SMALL-4", parent_id="C2A-BASE", operator="small_resource_conflict")
    fourth_validation = validate_candidate(fourth, prepared)
    cases.append({"case_id": "Q4-Small-4 resource conflict", "expected": "PASS with shortage report",
                  "actual": f"{fourth_validation['status']} with shortage={sum(fourth['shortages'].values())}",
                  "purpose": "inventory shortfall is reported as a Q4 resource configuration result, not misclassified as hard infeasibility"})
    passed = cases[0]["actual"] == "PASS" and cases[1]["actual"] == "PASS" and cases[2]["actual"] == "FAIL" and fourth_validation["status"] == "PASS" and sum(fourth["shortages"].values()) > 0
    result = {"phase": "Q4 small-case validation", "status": "PASS" if passed else "FAIL", "cases": cases}
    (results_root() / "q4_small_case_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_small_cases(), ensure_ascii=False, indent=2))
