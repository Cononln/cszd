"""Derive the formal Q3 tables solely from q3_final.json."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .q3_final import _root


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_final(root: Path) -> tuple[dict[str, Any], str]:
    path = root / "q3_final.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, hashlib.sha256(path.read_bytes()).hexdigest()


def write_tables() -> dict[str, Any]:
    root = _root()
    final, source_sha = _read_final(root)
    output = root / "tables"
    output.mkdir(parents=True, exist_ok=True)
    selected = final["selected_solution"]
    objective = selected["objective"]
    metrics = [
        {"metric": "Weighted delivery time", "value": objective["WTD"], "unit": "kg·s"},
        {"metric": "Transport makespan", "value": objective["transport_Cmax_s"], "unit": "s"},
        {"metric": "Joint makespan", "value": objective["joint_Cmax_s"], "unit": "s"},
        {"metric": "Transport energy", "value": objective["transport_energy_kwh"], "unit": "kWh"},
        {"metric": "Relay energy", "value": objective["relay_energy_kwh"], "unit": "kWh"},
        {"metric": "Total energy", "value": objective["total_energy_kwh"], "unit": "kWh"},
        {"metric": "Transport trips", "value": objective["transport_n_trips"], "unit": "count"},
        {"metric": "Relay sorties", "value": objective["relay_sorties"], "unit": "count"},
    ]
    _write_csv(output / "Q3_Table_01_FinalSolution.csv", metrics)
    checks: list[dict[str, Any]] = []
    for family, validation in (("transport", selected["transport_validation"]),
                               ("relay", selected["relay_validation"]),
                               ("joint", selected["joint_validation"])):
        for name, passed in validation.get("checks", {}).items():
            checks.append({"constraint_family": family, "constraint": name,
                           "status": "PASS" if passed else "FAIL"})
    _write_csv(output / "Q3_Table_02_ConstraintAudit.csv", checks)
    pool_rows: list[dict[str, Any]] = []
    all_solutions = [selected, *final.get("alternative_feasible_solutions", [])]
    for rank, solution in enumerate(all_solutions, 1):
        item = solution["objective"]
        pool_rows.append({"rank": rank, "solution_id": solution["solution_id"] if "solution_id" in solution else solution["candidate_id"],
                          "stage": solution.get("repair_stage"), "operator": solution.get("operator"),
                          "WTD": item["WTD"], "joint_Cmax_s": item["joint_Cmax_s"],
                          "total_energy_kwh": item["total_energy_kwh"],
                          "transport_n_trips": item["transport_n_trips"], "relay_sorties": item["relay_sorties"]})
    _write_csv(output / "Q3_Table_03_FeasiblePool.csv", pool_rows)
    markdown = ["# Q3 Formal Tables", "", "All values are derived directly from `q3_final.json`.", "",
                "## Selected solution", "", "| Metric | Value | Unit |", "|---|---:|---|"]
    markdown.extend(f"| {row['metric']} | {float(row['value']):.6f} | {row['unit']} |" for row in metrics)
    markdown.extend(["", "## Constraint audit", "", "| Family | PASS |", "|---|---:|"])
    for family in ("transport", "relay", "joint"):
        family_rows = [row for row in checks if row["constraint_family"] == family]
        markdown.append(f"| {family} | {sum(row['status'] == 'PASS' for row in family_rows)}/{len(family_rows)} |")
    (output / "Q3_Formal_Tables.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    artifacts = ["Q3_Table_01_FinalSolution.csv", "Q3_Table_02_ConstraintAudit.csv", "Q3_Table_03_FeasiblePool.csv", "Q3_Formal_Tables.md"]
    manifest = {"status": "PASS", "source": "q3_final.json", "source_sha256": source_sha,
                "artifacts": artifacts, "table_count": 3}
    (output / "q3_table_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(write_tables(), ensure_ascii=False, indent=2))
