"""Build the single formal Q3 result source from persisted C2 evidence."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any


OBJECTIVE_KEYS = ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_sorties")


def _root() -> Path:
    configured = os.environ.get("Q3_RESULTS_DIR")
    path = Path(configured).resolve() if configured else Path(__file__).resolve().parents[2] / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(name: str) -> dict[str, Any]:
    return json.loads((_root() / name).read_text(encoding="utf-8"))


def _valid(row: dict[str, Any]) -> bool:
    repaired = row.get("repaired", {})
    return bool(row.get("feasible_seed_found") and row.get("joint_status") == "PASS" and
                repaired.get("transport_validation", {}).get("status") == "PASS" and
                repaired.get("relay_validation", {}).get("decoder_validation_status") == "PASS" and
                all(repaired.get("relay_validation", {}).get("checks", {}).values()) and
                repaired.get("joint", {}).get("status") == "PASS" and
                all(repaired.get("joint", {}).get("checks", {}).values()))


def _metrics(row: dict[str, Any]) -> dict[str, float]:
    repaired = row["repaired"]
    tm = repaired["transport_validation"]["metrics"]
    rm = repaired["relay"]["metrics"]
    return {"WTD": float(tm["WTD"]), "joint_Cmax_s": max(float(tm["Cmax_s"]), float(rm["relay_cmax_s"])),
            "total_energy_kwh": float(tm["total_energy_kwh"]) + float(rm["relay_energy_kwh"]),
            "transport_n_trips": int(tm["n_trips"]), "relay_sorties": int(rm["relay_sortie_count"]),
            "transport_Cmax_s": float(tm["Cmax_s"]), "transport_energy_kwh": float(tm["total_energy_kwh"]),
            "relay_energy_kwh": float(rm["relay_energy_kwh"])}


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _fleet_configuration(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trip in state.get("trips", []):
        gtype = str(trip.get("gtype", "UNKNOWN"))
        counts[gtype] = counts.get(gtype, 0) + 1
    return dict(sorted(counts.items()))


def _failure_taxonomy(failures: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for failure in failures:
        categories: list[str] = []
        violations = failure.get("violations") or {}
        for group, values in violations.items():
            if isinstance(values, list):
                for value in values:
                    category = f"{group}:{value}"
                    counts[category] = counts.get(category, 0) + 1
                    categories.append(category)
        if not categories:
            reason = str(failure.get("failure_reason") or "other hard constraint")
            counts[reason] = counts.get(reason, 0) + 1
            categories.append(reason)
        rows.append({"candidate_id": failure.get("candidate_id"), "categories": categories,
                     "failure_reason": failure.get("failure_reason")})
    return {"counts": dict(sorted(counts.items())), "candidate_failures": rows}


def build_final() -> dict[str, Any]:
    c2a = _read("q3_c2a_candidates.json")
    c2b = _read("q3_c2b_candidates.json") if (_root() / "q3_c2b_candidates.json").exists() else {"candidates": []}
    rows = []
    for source, payload in (("C2-A", c2a), ("C2-B", c2b)):
        for row in payload.get("candidates", []):
            if _valid(row):
                item = dict(row)
                item["repair_stage"] = source
                item["objective"] = _metrics(row)
                rows.append(item)
    rows.sort(key=lambda row: tuple(row["objective"][key] for key in OBJECTIVE_KEYS) + (row["candidate_id"],))
    if not rows:
        raise RuntimeError("no validator-PASS candidate available for q3_final.json")
    selected = rows[0]
    alternatives = [{"candidate_id": row["candidate_id"], "repair_stage": row["repair_stage"],
                     "objective": row["objective"], "operator": row["operator"]} for row in rows[1:]]
    failure_rows = []
    for source, payload in (("C2-A", c2a), ("C2-B", c2b)):
        for row in payload.get("candidates", []):
            if not _valid(row):
                failure_rows.append({"source": source, "candidate_id": row.get("candidate_id"),
                                     "joint_status": row.get("joint_status"),
                                     "violations": row.get("repaired", {}).get("violations", {}),
                                     "failure_reason": (row.get("repaired", {}).get("joint") or {}).get("reason")})
    taxonomy = _failure_taxonomy(failure_rows)
    selected_state = selected["transport_state"]
    final = {
        "metadata": {"phase": "Q3-C", "method": "C2 validated temporal repair + bounded C2-B",
                      "candidate_spacing_m": 1500.0, "formal_optimizer_entered": False,
                      "git_revision": _git_revision(), "q3_final_schema": "1.1"},
        "q2_frozen_reference": {"state_source": "implementation/q2/results/q2_solution_trips.csv + boxes.csv",
                                 "transport_physics_modified": False},
        "q3_method_version": "C2-A/C2-B validated seed builder",
        "c2a_summary": {"candidate_count": c2a.get("candidate_count"),
                         "joint_feasible_count": c2a.get("joint_feasible_count"),
                         "status": c2a.get("status")},
        "c2b_summary": {"candidate_count": c2b.get("candidate_count", 0),
                         "joint_feasible_count": c2b.get("joint_feasible_count", 0),
                         "status": c2b.get("status", "NOT_RUN")},
        "selected_solution": {"solution_id": selected["candidate_id"], "repair_stage": selected["repair_stage"],
                               "operator": selected["operator"], "objective": selected["objective"],
                               "fleet_configuration": _fleet_configuration(selected_state),
                               "route_reference": "Q2-FORMAL transport_state; unchanged route structure",
                               "transport_state": selected["transport_state"],
                               "schedule": selected["repaired"]["schedule"],
                               "relay": selected["repaired"]["relay"],
                               "transport_validation": selected["repaired"]["transport_validation"],
                               "relay_validation": selected["repaired"]["relay_validation"],
                               "joint_validation": selected["repaired"]["joint"]},
        "alternative_feasible_solutions": alternatives,
        "failure_statistics": {"candidate_count": len(rows) + len(failure_rows),
                                "validator_pass_count": len(rows), "failure_count": len(failure_rows),
                                "failures": failure_rows},
        "failure_taxonomy": taxonomy,
        "provenance": {"source_files": ["q3_c2a_candidates.json", "q3_c2b_candidates.json"],
                        "source_of_numbers": "real Q2 validator + real Q3-B decoder + independent validators",
                        "formal_result_source": "q3_final.json"},
    }
    return final


def write_final() -> dict[str, Any]:
    result = build_final()
    root = _root()
    (root / "q3_final.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    feasible_rows = []
    for row in [result["selected_solution"], *result.get("alternative_feasible_solutions", [])]:
        feasible_rows.append(row)
    (root / "q3_feasible_pool.json").write_text(json.dumps({"source": "q3_final.json", "solutions": feasible_rows},
                                                               ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "q3_failure_taxonomy.json").write_text(json.dumps(result["failure_taxonomy"],
                                                                ensure_ascii=False, indent=2), encoding="utf-8")
    return result
