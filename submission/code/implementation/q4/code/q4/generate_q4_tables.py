"""Formal Q4 tables derived only from q4_final.json."""
from __future__ import annotations

import csv
import hashlib
import json

from .q3_adapter import results_root


def generate_tables() -> dict:
    root = results_root(); source = root / "q4_final.json"; final = json.loads(source.read_text(encoding="utf-8"))
    out = root / "tables"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for key, selected in final["selected_solution"].items():
        rows.append({"group_count": key, "solution_id": selected["solution_id"], "state_signature": selected["state_signature"],
                     **selected["objective"], "service_area_groups": json.dumps([g["service_areas"] for g in selected["derived_state"]["groups"]], ensure_ascii=False),
                     "shortages": json.dumps(selected["derived_state"]["shortages"], ensure_ascii=False)})
    with (out / "Q4_Table_01_SelectedConfigurations.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    detail = []
    for key, selected in final["selected_solution"].items():
        for group in selected["derived_state"]["groups"]:
            detail.append({"group_count": key, "group_id": group["group_id"], "service_areas": ",".join(group["service_areas"]),
                           "transport_uavs": ",".join(group["resources"]["transport_uavs"]), "batteries": ",".join(group["resources"]["batteries"]),
                           "relay_uavs": ",".join(group["resources"]["relay_uavs"]), "relay_energy_components": ",".join(group["resources"]["relay_energy_components"]),
                           "workload_s": group["workload_s"]})
    with (out / "Q4_Table_02_GroupResources.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail[0])); writer.writeheader(); writer.writerows(detail)
    md = ["# Q4 Formal Tables", "", "All values are derived directly from `q4_final.json`.", "", "| Groups | Selected solution | Resource units | Shortage units | Imbalance |", "|---:|---|---:|---:|---:|"]
    md.extend(f"| {row['group_count']} | {row['solution_id']} | {row['total_resource_units']} | {row['total_shortage_units']} | {row['imbalance_ratio']:.6f} |" for row in rows)
    (out / "Q4_Formal_Tables.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    artifacts = ["Q4_Table_01_SelectedConfigurations.csv", "Q4_Table_02_GroupResources.csv", "Q4_Formal_Tables.md"]
    manifest = {"status": "PASS", "source": "q4_final.json", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "artifacts": artifacts, "table_count": 2}
    (out / "q4_table_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
