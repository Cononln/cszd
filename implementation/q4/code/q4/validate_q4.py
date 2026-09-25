"""Independent Q4 validator; recomputes all partition-derived quantities."""
from __future__ import annotations

from typing import Any

from .q4_model import canonical_q4_state_signature, evaluate_partition, prepare_state


def validate_candidate(candidate: dict[str, Any], prepared: dict[str, Any] | None = None) -> dict[str, Any]:
    prepared = prepared or prepare_state()
    groups = tuple(tuple(int(component) for component in group) for group in candidate["changed_variables"]["component_groups"])
    recomputed = evaluate_partition(prepared, groups, candidate_id=candidate["candidate_id"],
                                    parent_id=candidate["parent_id"], operator=candidate["operator"])
    checks = {
        "state_signature_matches": recomputed["state_signature"] == candidate.get("state_signature") == canonical_q4_state_signature(groups),
        "group_count_matches": recomputed["n_groups"] == candidate.get("n_groups"),
        "groups_match": recomputed["groups"] == candidate.get("groups"),
        "resource_requirements_match": recomputed["resource_requirements"] == candidate.get("resource_requirements"),
        "shortages_match": recomputed["shortages"] == candidate.get("shortages"),
        "objective_matches": recomputed["objective"] == candidate.get("objective"),
        "hard_constraints_recomputed": all(recomputed["hard_constraint_checks"].values()),
        "upstream_reference_matches": candidate.get("upstream_q3_reference") == prepared["interface"]["selected_solution_id"],
    }
    return {"candidate_id": candidate["candidate_id"], "state_signature": candidate.get("state_signature"),
            "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "recomputed_objective": recomputed["objective"], "recomputed_shortages": recomputed["shortages"]}


def validate_final(selected: dict[str, Any], prepared: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = {"candidate_id": selected["solution_id"], "parent_id": selected["parent_id"],
                 "operator": selected["operator"], "state_signature": selected["state_signature"],
                 "changed_variables": selected["decision_variables"], "n_groups": len(selected["derived_state"]["groups"]),
                 "groups": selected["derived_state"]["groups"], "resource_requirements": selected["derived_state"]["resource_requirements"],
                 "shortages": selected["derived_state"]["shortages"], "objective": selected["objective"],
                 "upstream_q3_reference": selected["upstream_q3_reference"]}
    result = validate_candidate(candidate, prepared)
    result["status"] = "PASS" if result["status"] == "PASS" and selected.get("validator_status") == "PASS" else "FAIL"
    return result
