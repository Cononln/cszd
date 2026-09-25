"""Refresh Q4 provenance after its required re-enumeration on new Q3 input."""
from __future__ import annotations

import json
import subprocess
from typing import Any

from .generate_q4_figures import generate_figures
from .generate_q4_tables import generate_tables
from .q3_adapter import load_q3_selected_solution, results_root
from .q4_model import prepare_state
from .validate_q4 import validate_final


def _revision() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def refresh() -> dict[str, Any]:
    root = results_root()
    final_path = root / "q4_final.json"
    final = json.loads(final_path.read_text(encoding="utf-8"))
    refresh_audit = json.loads((root / "q4_q3_upstream_refresh_audit.json").read_text(encoding="utf-8"))
    interface = load_q3_selected_solution()
    prepared = prepare_state(interface)
    selected_validations = {key: validate_final(row, prepared) for key, row in final["selected_solution"].items()}
    if not all(row["status"] == "PASS" for row in selected_validations.values()):
        raise RuntimeError("refreshed Q3 state invalidates the recorded Q4 selected solution")
    final["metadata"]["git_revision"] = _revision()
    final["q3_upstream_reference"] = interface
    final["q3_selected_solution_id"] = interface["selected_solution_id"]
    final["validator_result"] = selected_validations
    final["q4_method"]["candidate_pool_reuse_validated"] = False
    final["q4_method"]["upstream_change_resolution"] = "Q4_REENUMERATION"
    final["provenance"]["q3_upstream_refresh"] = {
        "audit_file": "q4_q3_upstream_refresh_audit.json",
        "historical_semantic_equal": refresh_audit["semantic_equal"],
        "q4_reenumeration_required": True,
        "q4_reenumeration_completed": True,
        "candidate_pool_reuse_validated": False,
    }
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    figures = generate_figures()
    tables = generate_tables()
    report: dict[str, Any] = {"status": "PASS", "q3_selected_solution_id": interface["selected_solution_id"],
                              "selected_validations": selected_validations, "figures": figures, "tables": tables}
    (root / "q4_q3_upstream_refresh_revalidation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))
