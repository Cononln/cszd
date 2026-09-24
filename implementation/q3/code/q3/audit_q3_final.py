"""Independent final Q3 audit; it does not trust stored PASS flags."""
from __future__ import annotations

import json
import os
import subprocess
import hashlib
from pathlib import Path
from typing import Any

from .q3_final import _root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _delivery_checks(root: Path, final_path: Path) -> dict[str, bool]:
    figures = root / "figures" / "q3_figure_manifest.json"
    tables = root / "tables" / "q3_table_manifest.json"
    if not figures.exists() or not tables.exists():
        return {"formal_figure_manifest_present": False, "formal_table_manifest_present": False,
                "figures_read_only_q3_final": False, "tables_read_only_q3_final": False,
                "figure_qa_pass": False, "all_manifest_artifacts_present": False}
    figure_manifest = json.loads(figures.read_text(encoding="utf-8"))
    table_manifest = json.loads(tables.read_text(encoding="utf-8"))
    artifact_paths = [root / "figures" / str(name) for name in figure_manifest.get("artifacts", [])]
    artifact_paths.extend(root / "tables" / str(name) for name in table_manifest.get("artifacts", []))
    source_hash = _sha256(final_path)
    return {
        "formal_figure_manifest_present": True,
        "formal_table_manifest_present": True,
        "figures_read_only_q3_final": figure_manifest.get("source") == "q3_final.json" and
                                        figure_manifest.get("source_sha256") == source_hash,
        "tables_read_only_q3_final": table_manifest.get("source") == "q3_final.json" and
                                       table_manifest.get("source_sha256") == source_hash,
        "figure_qa_pass": figure_manifest.get("status") == "PASS",
        "all_manifest_artifacts_present": all(path.exists() and path.stat().st_size > 0 for path in artifact_paths),
    }
from .validate_q3_c2 import validate_q3_c2


def audit(*, require_deliverables: bool = False) -> dict[str, Any]:
    root = _root()
    final_path = root / "q3_final.json"
    result = json.loads(final_path.read_text(encoding="utf-8"))
    independent = validate_q3_c2(final_path)
    changed = subprocess.check_output(["git", "diff", "--name-only", "d98635b..HEAD"], text=True).splitlines()
    forbidden = [path for path in changed if path.startswith(("implementation/q1/", "implementation/q2/")) or
                 path.startswith("implementation/q3/code/q3/audit_q3_a.py") or
                 path.startswith("implementation/q3/code/q3/relay_")]
    selected = result["selected_solution"]
    objective = selected["objective"]
    tm = independent["transport"]["metrics"]
    rm = independent["relay"]["metrics"]
    source_numbers_consistent = (
        abs(float(objective["WTD"]) - float(tm["WTD"])) < 1e-6 and
        abs(float(objective["transport_Cmax_s"]) - float(tm["Cmax_s"])) < 1e-6 and
        abs(float(objective["transport_energy_kwh"]) - float(tm["total_energy_kwh"])) < 1e-6 and
        int(objective["transport_n_trips"]) == int(tm["n_trips"]) and
        int(objective["relay_sorties"]) == int(rm["relay_sortie_count"]) and
        abs(float(objective["relay_energy_kwh"]) - float(rm["relay_energy_kwh"])) < 1e-6 and
        abs(float(objective["total_energy_kwh"]) - float(tm["total_energy_kwh"]) - float(rm["relay_energy_kwh"])) < 1e-6
    )
    csv_path = root / "q3_c2_transport_trips.csv"
    csv_count = sum(1 for _ in csv_path.open("r", encoding="utf-8-sig")) - 1 if csv_path.exists() else -1
    checks = {
        "q2_frozen_files_untouched": not forbidden,
        "independent_validator_pass": independent["status"] == "PASS",
        "all_hard_constraints_pass": independent["checks"]["joint_independent_validator_pass"],
        "full_communication_zero_outage": independent["checks"]["zero_communication_outage"],
        "source_numbers_consistent": source_numbers_consistent,
        "schedule_csv_complete": csv_count == int(objective["transport_n_trips"]),
        "no_formal_optimizer_entered": result["metadata"].get("formal_optimizer_entered") is False,
        "single_formal_source_declared": result["provenance"].get("formal_result_source") == "q3_final.json",
        "failure_taxonomy_present": "failure_taxonomy" in result,
    }
    delivery = _delivery_checks(root, final_path)
    if require_deliverables:
        checks.update(delivery)
    report = {"phase": "Q3-final-audit", "status": "PASS" if all(checks.values()) else "FAIL",
              "checks": checks, "independent_validation": independent,
              "delivery_checks": delivery, "require_deliverables": require_deliverables,
              "changed_files_since_c1": changed, "forbidden_changed_files": forbidden,
              "selected_solution_id": selected["solution_id"]}
    (root / "q3_final_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Independently audit the formal Q3 result.")
    parser.add_argument("--require-deliverables", action="store_true",
                        help="require formal figures/tables and their source mapping")
    args = parser.parse_args()
    print(json.dumps(audit(require_deliverables=args.require_deliverables), ensure_ascii=False, indent=2))
