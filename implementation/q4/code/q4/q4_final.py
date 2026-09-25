"""Build the single formal Q4 result source from the Q4 search evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .problem_audit import problem_definition
from .q3_adapter import results_root


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def build_final(model: dict[str, Any], interface_gate: dict[str, Any]) -> dict[str, Any]:
    prepared = model["prepared"]
    selected = {key: value for key, value in model["selected"].items()}
    selected_summary = {}
    for key, row in selected.items():
        selected_summary[key] = {
            "solution_id": row["candidate_id"], "parent_id": row["parent_id"], "stage": "Q4-F",
            "operator": row["operator"], "state_signature": row["state_signature"],
            "upstream_q3_reference": row["upstream_q3_reference"],
            "decision_variables": row["changed_variables"], "unchanged_frozen_variables": row["unchanged_frozen_variables"],
            "derived_state": {"groups": row["groups"],
            "resource_requirements": row["resource_requirements"], "inventory": row["inventory"],
            "shortages": row["shortages"], "workload": row["workload"]},
            "objective": row["objective"], "hard_constraint_checks": row["hard_constraint_checks"],
            "validator_status": "PASS", "validator_result": row["validator_result"],
        }
    source_path = prepared["interface"]["source_file"]
    final = {
        "metadata": {"phase": "Q4", "method": "exact enumeration of legal component partitions",
                     "formal_solver": "deterministic exhaustive partition enumeration",
                     "git_revision": _git_revision(), "q4_final_schema": "1.0"},
        "q3_upstream_reference": prepared["interface"],
        "q3_selected_solution_id": prepared["interface"]["selected_solution_id"],
        "q4_problem_definition": problem_definition(),
        "q4_method": {"description": "Enumerate all unlabeled nonempty partitions of frozen multi-stop service-area components for k=2 and k=3.",
                       "selection_rule": "minimize (total shortage units, total independent resource units, workload imbalance ratio, state signature)",
                       "random_seeds": [], "q3_state_modified": False},
        "q4_baseline": {key: model["baseline"][key] for key in ("candidate_id", "state_signature", "objective", "shortages", "hard_constraint_checks", "validator_status", "validator_result")},
        "search_statistics": {"2": model["summaries"]["2"], "3": model["summaries"]["3"],
                              "total_candidates": len(model["all_rows"]), "total_feasible": len(model["feasible"]),
                              "runtime_s": model["search_runtime_s"], "candidate_state_signatures_unique": model["candidate_state_signatures_unique"]},
        "failure_taxonomy_summary": model["failure_taxonomy"],
        "feasible_pool_summary": {"source": "q4_final.json", "state_level_unique_count": len(model["pool"]),
                                  "validator_pass_count": len(model["pool"]), "validator_fail_count": len(model["all_rows"]) - len(model["pool"])},
        "selected_solution": selected_summary,
        "objective_components": {key: row["objective"] for key, row in selected.items()},
        "hard_constraint_checks": {key: row["hard_constraint_checks"] for key, row in selected.items()},
        "validator_result": {key: row["validator_result"] for key, row in selected.items()},
        "random_seeds": [],
        "provenance": {"source_of_q3": source_path, "source_of_formal_numbers": "q4_final.json",
                        "q3_search_history_used": False, "q3_selected_solution_only": True,
                        "q4_candidate_source": "exact legal partition enumeration"},
    }
    return final


def write_final(model: dict[str, Any], interface_gate: dict[str, Any]) -> dict[str, Any]:
    root = results_root()
    final = build_final(model, interface_gate)
    final_path = root / "q4_final.json"
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    pool = []
    for row in model["pool"]:
        pool.append(row)
    (root / "q4_feasible_pool.json").write_text(json.dumps({"source": "q4_final.json", "solutions": pool}, ensure_ascii=False, indent=2), encoding="utf-8")
    return final
