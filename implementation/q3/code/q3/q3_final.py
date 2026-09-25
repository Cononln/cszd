"""Build the single formal Q3 result source from persisted C2 evidence."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from .c2_seed_builder import canonical_transport_signature


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


def _failure_category(family: str, source_check: str) -> str:
    """Translate a failed validator check into a human-meaningful category."""
    known = {
        ("transport", "mass_pass"): "TRANSPORT_MASS_VIOLATION",
        ("transport", "volume_pass"): "TRANSPORT_VOLUME_VIOLATION",
        ("transport", "route_energy_recomputed"): "TRANSPORT_ROUTE_ENERGY_INCONSISTENCY",
        ("transport", "energy_pass"): "TRANSPORT_ENERGY_VIOLATION",
        ("relay", "energy_pass"): "RELAY_ENERGY_VIOLATION",
    }
    if (family, source_check) in known:
        return known[(family, source_check)]
    safe = "".join(character if character.isalnum() else "_" for character in source_check.upper())
    return f"{family.upper()}_CONSTRAINT_VIOLATION_{safe.removesuffix('_PASS')}"


def _failure_taxonomy(failures: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for failure in failures:
        evidence: list[dict[str, Any]] = []
        violations = failure.get("violations") or {}
        for group, values in violations.items():
            if isinstance(values, list):
                for value in values:
                    category = _failure_category(str(group), str(value))
                    counts[category] = counts.get(category, 0) + 1
                    evidence.append({"category": category, "source_check": str(value),
                                     "source_value": False, "constraint_family": str(group)})
        if not evidence:
            category = "JOINT_VALIDATION_FAILURE"
            counts[category] = counts.get(category, 0) + 1
            evidence.append({"category": category, "source_check": "joint_validator_pass",
                             "source_value": False, "constraint_family": "joint"})
        rows.append({"candidate_id": failure.get("candidate_id"),
                     "state_signature": failure.get("state_signature"),
                     "evidence": evidence,
                     "failure_reason": failure.get("failure_reason")})
    return {"counts": dict(sorted(counts.items())), "candidate_failures": rows}


def _pool_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "solution_id": row["candidate_id"],
        "parent_id": row["parent_id"],
        "stage": row["repair_stage"],
        "operator": row["operator"],
        "state_signature": row["state_signature"],
        "objective": row["objective"],
        "validator_status": "PASS",
    }


def build_final() -> dict[str, Any]:
    c2a = _read("q3_c2a_candidates.json")
    c2b = _read("q3_c2b_candidates.json") if (_root() / "q3_c2b_candidates.json").exists() else {"candidates": []}
    rows = []
    seen_signatures: set[str] = set()
    for source, payload in (("C2-A", c2a), ("C2-B", c2b)):
        for row in payload.get("candidates", []):
            if _valid(row):
                item = dict(row)
                item["repair_stage"] = source
                item["objective"] = _metrics(row)
                item["state_signature"] = item.get("state_signature") or canonical_transport_signature(
                    item["transport_state"])
                if item["state_signature"] not in seen_signatures:
                    seen_signatures.add(item["state_signature"])
                    rows.append(item)
    rows.sort(key=lambda row: tuple(row["objective"][key] for key in OBJECTIVE_KEYS) + (row["candidate_id"],))
    if not rows:
        raise RuntimeError("no validator-PASS candidate available for q3_final.json")
    selected = rows[0]
    pool = [_pool_entry(row) for row in rows]
    alternatives = pool[1:]
    failure_rows = []
    for source, payload in (("C2-A", c2a), ("C2-B", c2b)):
        for row in payload.get("candidates", []):
            if not _valid(row):
                failure_rows.append({"source": source, "candidate_id": row.get("candidate_id"),
                                     "joint_status": row.get("joint_status"),
                                     "state_signature": row.get("state_signature") or canonical_transport_signature(
                                         row.get("transport_state", {})),
                                     "violations": row.get("repaired", {}).get("violations", {}),
                                     "failure_reason": (row.get("repaired", {}).get("joint") or {}).get("reason")})
    taxonomy = _failure_taxonomy(failure_rows)
    selected_state = selected["transport_state"]
    final = {
        "metadata": {"phase": "Q3-C", "method": "C2 validated temporal repair + bounded C2-B",
                      "candidate_spacing_m": 1500.0, "formal_optimizer_entered": False,
                      "git_revision": _git_revision(), "q3_final_schema": "1.2"},
        "q2_frozen_reference": {"state_source": "implementation/q2/results/q2_solution_trips.csv + boxes.csv",
                                 "transport_physics_modified": False},
        "q3_method_version": "C2-A/C2-B validated seed builder",
        "c2a_summary": {"generated_raw_count": c2a.get("generated_raw_count"),
                         "noop_removed_count": c2a.get("noop_removed_count"),
                         "duplicate_removed_count": c2a.get("duplicate_removed_count"),
                         "unique_candidate_count": c2a.get("unique_candidate_count"),
                         "candidate_count": c2a.get("candidate_count"),
                         "joint_feasible_count": c2a.get("joint_feasible_count"),
                         "status": c2a.get("status")},
        "c2b_summary": {"generated_raw_count": c2b.get("generated_raw_count", 0),
                         "noop_removed_count": c2b.get("noop_removed_count", 0),
                         "duplicate_removed_count": c2b.get("duplicate_removed_count", 0),
                         "unique_candidate_count": c2b.get("unique_candidate_count", 0),
                         "candidate_count": c2b.get("candidate_count", 0),
                         "joint_feasible_count": c2b.get("joint_feasible_count", 0),
                         "status": c2b.get("status", "NOT_RUN")},
        "selected_solution": {"solution_id": selected["candidate_id"], "parent_id": selected["parent_id"],
                               "stage": selected["repair_stage"], "repair_stage": selected["repair_stage"],
                               "operator": selected["operator"], "state_signature": selected["state_signature"],
                               "validator_status": "PASS", "objective": selected["objective"],
                               "fleet_configuration": _fleet_configuration(selected_state),
                               "route_reference": "Q2-FORMAL transport_state; unchanged route structure",
                               "transport_state": selected["transport_state"],
                               "schedule": selected["repaired"]["schedule"],
                               "relay": selected["repaired"]["relay"],
                               "transport_validation": selected["repaired"]["transport_validation"],
                               "relay_validation": selected["repaired"]["relay_validation"],
                               "joint_validation": selected["repaired"]["joint"]},
        "alternative_feasible_solutions": alternatives,
        "feasible_pool": pool,
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
    (root / "q3_feasible_pool.json").write_text(json.dumps({"source": "q3_final.json",
                                                               "solutions": result["feasible_pool"]},
                                                               ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "q3_failure_taxonomy.json").write_text(json.dumps(result["failure_taxonomy"],
                                                                ensure_ascii=False, indent=2), encoding="utf-8")
    return result
