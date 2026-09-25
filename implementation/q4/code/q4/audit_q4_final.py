"""Independent final audit for formal Q4 artifacts."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .q3_adapter import load_q3_selected_solution, q3_audit_path, results_root
from .q4_model import prepare_state
from .validate_q4 import validate_final


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(*, require_deliverables: bool = False) -> dict[str, Any]:
    root = results_root(); final_path = root / "q4_final.json"; final = json.loads(final_path.read_text(encoding="utf-8"))
    current_q3 = load_q3_selected_solution(); q3audit = json.loads(q3_audit_path().read_text(encoding="utf-8"))
    prepared = prepare_state(current_q3)
    selected = final["selected_solution"]
    validations = {key: validate_final(value, prepared) for key, value in selected.items()}
    pool = json.loads((root / "q4_feasible_pool.json").read_text(encoding="utf-8")).get("solutions", [])
    candidates = []
    for n in (2, 3):
        candidates.extend(json.loads((root / f"q4_{n}group_candidates.json").read_text(encoding="utf-8")).get("candidates", []))
    candidate_signatures = [row.get("state_signature") for row in candidates]
    pool_signatures = [row.get("state_signature") for row in pool]
    requirements = {"solution_id", "parent_id", "state_signature", "operator", "upstream_q3_reference", "decision_variables", "unchanged_frozen_variables", "derived_metrics", "objective", "hard_constraint_checks", "validator_status"}
    failure = final.get("failure_taxonomy_summary", {})
    failure_valid = all(row.get("category") and row.get("category") != "unknown" and row.get("source_value") is False
                        for row in failure.get("candidate_failures", []))
    changed = subprocess.check_output(["git", "diff", "--name-only", "869bcbc..HEAD"], text=True).splitlines()
    working = subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines()
    forbidden = [path for path in changed + working if path.startswith(("implementation/q1/", "implementation/q2/", "implementation/q3/"))]
    checks: dict[str, bool] = {
        "q3_upstream_reference_valid": q3audit.get("status") == "PASS" and all(q3audit.get("checks", {}).values()),
        "q3_selected_solution_unchanged": final["q3_selected_solution_id"] == current_q3["selected_solution_id"] and final["q3_upstream_reference"]["selected_solution_fingerprint"] == current_q3["selected_solution_fingerprint"],
        "q3_frozen_files_untouched": not forbidden,
        "q4_variables_legal": final["q4_problem_definition"].get("status") == "PASS" and len(final["q4_problem_definition"].get("new_decision_variables", [])) == 1,
        "q4_validator_independent": all(value["status"] == "PASS" for value in validations.values()),
        "all_hard_constraints_pass": all(all(value["checks"].values()) for value in validations.values()),
        "objective_recomputed": all(value["checks"].get("objective_matches", False) for value in validations.values()),
        "source_numbers_consistent": all(value["checks"].get("resource_requirements_match", False) and value["checks"].get("shortages_match", False) for value in validations.values()),
        "candidate_state_signatures_unique": len(candidate_signatures) == len(set(candidate_signatures)),
        "feasible_pool_signatures_unique": len(pool_signatures) == len(set(pool_signatures)) and all(requirements.issubset(row) for row in pool),
        "no_noop_candidates": all(row.get("changed_variables", {}).get("component_groups") for row in candidates),
        "frozen_variables_explicit": all(row.get("unchanged_frozen_variables") for row in candidates) and all(
            row.get("unchanged_frozen_variables") for row in pool) and all(
            row.get("unchanged_frozen_variables") for row in selected.values()),
        "failure_taxonomy_valid": failure_valid,
        "single_formal_source": final.get("provenance", {}).get("source_of_formal_numbers") == "q4_final.json",
    }
    delivery = {"figures_read_only_q4_final": False, "tables_read_only_q4_final": False, "figure_qa_pass": False,
                "all_deliverables_present": False}
    figure_manifest = root / "figures" / "q4_figure_manifest.json"; table_manifest = root / "tables" / "q4_table_manifest.json"
    if figure_manifest.exists() and table_manifest.exists():
        figures = json.loads(figure_manifest.read_text(encoding="utf-8")); tables = json.loads(table_manifest.read_text(encoding="utf-8")); source_sha = _sha(final_path)
        artifacts = [root / "figures" / name for name in figures.get("artifacts", [])] + [root / "tables" / name for name in tables.get("artifacts", [])]
        delivery = {"figures_read_only_q4_final": figures.get("source") == "q4_final.json" and figures.get("source_sha256") == source_sha,
                    "tables_read_only_q4_final": tables.get("source") == "q4_final.json" and tables.get("source_sha256") == source_sha,
                    "figure_qa_pass": figures.get("status") == "PASS",
                    "all_deliverables_present": all(path.exists() and path.stat().st_size > 0 for path in artifacts)}
    if require_deliverables: checks.update(delivery)
    report = {"phase": "Q4 final audit", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
              "delivery_checks": delivery, "selected_validations": validations, "changed_files": changed + working,
              "forbidden_changed_files": forbidden, "require_deliverables": require_deliverables}
    (root / "q4_final_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
