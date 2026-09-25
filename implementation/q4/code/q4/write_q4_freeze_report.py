"""Write the Q4 freeze report from formal and clean-reproduction evidence."""
from __future__ import annotations

import json
from pathlib import Path

from .q3_adapter import q4_root, results_root


def write_report() -> Path:
    root = results_root(); final = json.loads((root / "q4_final.json").read_text(encoding="utf-8")); audit = json.loads((root / "q4_final_audit.json").read_text(encoding="utf-8"))
    clean_path = q4_root() / "reproducibility" / "clean_results" / "q4_reproduction_report.json"
    clean = json.loads(clean_path.read_text(encoding="utf-8")) if clean_path.exists() else {"status": "NOT RECORDED"}
    comparison_path = root / "q4_reproduction_comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8")) if comparison_path.exists() else {"status": "NOT RECORDED"}
    refresh_path = root / "q4_q3_upstream_refresh_audit.json"
    refresh = json.loads(refresh_path.read_text(encoding="utf-8")) if refresh_path.exists() else {}
    checks = audit["checks"]
    freeze = {"Q3 interface": checks.get("q3_upstream_reference_valid", False), "variable legality": checks.get("q4_variables_legal", False),
              "independent validator": checks.get("q4_validator_independent", False), "hard constraints": checks.get("all_hard_constraints_pass", False),
              "candidate integrity": checks.get("candidate_state_signatures_unique", False) and checks.get("no_noop_candidates", False),
              "feasible pool": checks.get("feasible_pool_signatures_unique", False), "final audit": audit["status"] == "PASS",
              "figures and tables": checks.get("figure_qa_pass", False) and checks.get("all_deliverables_present", False),
              "Q3 upstream refresh": checks.get("q3_upstream_change_handled", False),
              "clean reproduction": clean.get("status") == "PASS" and comparison.get("status") == "PASS",
              "Q3 frozen files": checks.get("q3_frozen_files_untouched", False)}
    lines = ["# Q4 Freeze Report", "", "## Upstream inheritance", "", f"- Q3 solution: `{final['q3_selected_solution_id']}`", "- Q4 reads only the selected Q3 formal solution.", "",
             "## Formal method", "", final["q4_method"]["description"], "", "## Selected configurations", "", "| Groups | Solution | Resource units | Shortage units | Workload imbalance |", "|---:|---|---:|---:|---:|"]
    for key, row in final["selected_solution"].items():
        objective = row["objective"]; lines.append(f"| {key} | `{row['solution_id']}` | {objective['total_resource_units']} | {objective['total_shortage_units']} | {objective['imbalance_ratio']:.6f} |")
    lines.extend(["", "## Search", ""])
    for key, summary in final["search_statistics"].items():
        if key in {"2", "3"}: lines.append(f"- {key} groups: {summary['unique_candidate_count']} legal unique candidates; {summary['feasible_count']} validator PASS")
    lines.extend(["", "## Q3 upstream refresh", "",
                  f"- old Q3 formal revision: `{refresh.get('old_q3_revision', 'UNKNOWN')}`",
                  f"- latest Q3 formal revision: `{refresh.get('new_q3_revision', 'UNKNOWN')}`",
                  f"- Q3 refreeze commit: `{refresh.get('q3_refreeze_head', 'UNKNOWN')}`",
                  f"- selected solution: `{refresh.get('selected_solution', {}).get('new_solution_id', 'UNKNOWN')}`",
                  f"- transport state unchanged: {'PASS' if refresh.get('transport_state_equal') else 'FAIL'}",
                  f"- transport schedule unchanged: {'PASS' if refresh.get('transport_schedule_equal') else 'FAIL'}",
                  f"- relay schedule unchanged: {'PASS' if refresh.get('relay_schedule_equal') else 'FAIL'}",
                  f"- core objectives unchanged: {'PASS' if refresh.get('core_objective_equal') else 'FAIL'}",
                  f"- Q4 re-enumeration required: {'YES' if not refresh.get('semantic_equal', True) else 'NO'}",
                  f"- Q4 re-enumeration completed: {'YES' if final.get('provenance', {}).get('q3_upstream_refresh', {}).get('q4_reenumeration_completed') else 'NO'}",
                  "", "## Freeze checks", ""])
    lines.extend(f"- [{'x' if value else ' '}] {name}" for name, value in freeze.items())
    frozen = all(freeze.values())
    lines.extend(["", "Q4 STATUS: FROZEN" if frozen else "Q4 STATUS: NOT FROZEN",
                  "UPSTREAM Q3 REFRESH: PASS" if frozen else "UPSTREAM Q3 REFRESH: FAIL"])
    path = root / "Q4_FREEZE_REPORT.md"; path.write_text("\n".join(lines) + "\n", encoding="utf-8"); return path
