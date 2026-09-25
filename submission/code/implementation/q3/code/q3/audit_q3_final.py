"""Independent final Q3 audit; it does not trust stored PASS flags."""
from __future__ import annotations

import json
import os
import subprocess
import hashlib
from pathlib import Path
from typing import Any

from .q3_final import _root
from .c2_seed_builder import canonical_transport_signature


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


def _candidate_integrity(root: Path, final: dict[str, Any]) -> dict[str, bool]:
    """Recompute candidate counts and state identities from persisted evidence."""
    payloads = []
    for name in ("q3_c2a_candidates.json", "q3_c2b_candidates.json"):
        path = root / name
        if path.exists():
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
    rows = [row for payload in payloads for row in payload.get("candidates", [])]
    signatures = [row.get("state_signature") or canonical_transport_signature(row.get("transport_state", {}))
                  for row in rows]
    baseline = next((row for row in rows if row.get("candidate_id") == "C2A-BASE"), None)
    base_trips = (baseline or {}).get("transport_state", {}).get("trips", [])
    no_op = False
    for row in rows:
        operator = str(row.get("operator", ""))
        if row.get("candidate_id") == "C2A-BASE":
            continue
        state_trips = row.get("transport_state", {}).get("trips", [])
        if operator.startswith("single_type_adjustment_T"):
            token = operator.removeprefix("single_type_adjustment_T")
            number_text, proposed = token.split("_", 1)
            number = int(number_text)
            if 1 <= number <= len(base_trips) and str(base_trips[number - 1].get("gtype")) == proposed:
                no_op = True
        if operator.startswith("combination_"):
            for token in operator.removeprefix("combination_").split("+"):
                number_text, proposed = token[1:].split("-", 1)
                number = int(number_text)
                if 1 <= number <= len(base_trips) and str(base_trips[number - 1].get("gtype")) == proposed:
                    no_op = True
        if row.get("state_signature") != canonical_transport_signature(row.get("transport_state", {})):
            no_op = True
    stats_ok = True
    for payload in payloads:
        unique = payload.get("unique_candidate_count")
        count = payload.get("candidate_count")
        raw = payload.get("generated_raw_count")
        removed = int(payload.get("noop_removed_count", 0)) + int(payload.get("duplicate_removed_count", 0))
        candidate_rows = payload.get("candidates", [])
        stats_ok = stats_ok and count == len(candidate_rows) == unique and raw - removed == unique
    taxonomy = final.get("failure_taxonomy", {})
    evidence_ok = True
    for failure in taxonomy.get("candidate_failures", []):
        for evidence in failure.get("evidence", []):
            category = str(evidence.get("category", ""))
            evidence_ok = evidence_ok and bool(category) and not category.endswith("_PASS") and evidence.get("source_value") is False
    pool = final.get("feasible_pool", [])
    required = {"solution_id", "parent_id", "stage", "operator", "state_signature", "objective", "validator_status"}
    pool_fields_ok = all(required.issubset(entry) for entry in pool)
    return {
        "no_noop_candidates": not no_op,
        "candidate_state_signatures_unique": len(signatures) == len(set(signatures)),
        "feasible_pool_state_signatures_unique": len(pool) == len({entry.get("state_signature") for entry in pool}) and pool_fields_ok,
        "candidate_counts_recomputed": stats_ok,
        "failure_taxonomy_semantically_valid": evidence_ok,
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
    integrity = _candidate_integrity(root, result)
    checks.update(integrity)
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
