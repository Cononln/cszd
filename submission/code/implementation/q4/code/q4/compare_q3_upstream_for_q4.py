"""Semantic comparison of the old and refrozen Q3 formal solutions for Q4.

Candidate-pool cleanup changes Q3 metadata, but it must not silently change
the selected transport/relay state inherited by Q4.  This module compares
only that inherited state, with an absolute float tolerance of 1e-9.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .q3_adapter import results_root


TOLERANCE = 1e-9


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _compare(left: Any, right: Any, path: str = "$") -> list[dict[str, Any]]:
    """Return compact semantic differences, treating close floats as equal."""
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        return [] if abs(float(left) - float(right)) <= TOLERANCE else [{"path": path, "old": left, "new": right}]
    if type(left) is not type(right):
        return [{"path": path, "old": left, "new": right}]
    if isinstance(left, dict):
        rows: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                rows.append({"path": f"{path}.{key}", "old": left.get(key), "new": right.get(key)})
            else:
                rows.extend(_compare(left[key], right[key], f"{path}.{key}"))
        return rows
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "old": {"length": len(left)}, "new": {"length": len(right)}}]
        rows = []
        for index, (old, new) in enumerate(zip(left, right)):
            rows.extend(_compare(old, new, f"{path}[{index}]"))
        return rows
    return [] if left == right else [{"path": path, "old": left, "new": right}]


def _selected_state(selected: dict[str, Any]) -> dict[str, Any]:
    """Canonical selected-solution state, excluding provenance/search metadata."""
    return {
        "transport_state": selected.get("transport_state", {}),
        "schedule": selected.get("schedule", {}),
        "relay": selected.get("relay", {}),
        "objective": selected.get("objective", {}),
        "fleet_configuration": selected.get("fleet_configuration", {}),
    }


def _transport_state(selected: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gtype": row.get("gtype"), "stop_sequence": row.get("stop_sequence", []),
             "boxes_by_stop": row.get("boxes_by_stop", {})}
            for row in selected.get("transport_state", {}).get("trips", [])]


def _transport_schedule(selected: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("trip_id", "gtype", "uid", "battery_id", "start_time_s", "departure_time_s", "return_time_s",
              "charge_start_s", "charge_end_s", "delivery_by_box_s")
    rows = [{field: row.get(field) for field in fields} for row in selected.get("schedule", {}).get("trip_records", [])]
    return sorted(rows, key=lambda row: str(row.get("trip_id")))


def _relay_schedule(selected: dict[str, Any]) -> dict[str, Any]:
    fields = ("sortie_id", "relay_id", "energy_component_id", "launch_start_s", "service_start_s", "service_end_s",
              "return_end_s", "charge_start_s", "charge_end_s", "demand_ids")
    sorties = [{field: row.get(field) for field in fields} for row in selected.get("relay", {}).get("relay_sorties", [])]
    coverage = [{"demand_id": row.get("demand_id"), "selected_sortie_id": row.get("selected_sortie_id"),
                 "scheduled_covered": row.get("scheduled_covered"), "full_replay_covered": row.get("full_replay_covered")}
                for row in selected.get("relay", {}).get("coverage_audit", [])]
    replay = [{"trip_id": row.get("trip_id"), "outage_duration_s": row.get("outage_duration_s"),
               "communication_feasible": row.get("communication_feasible")}
              for row in selected.get("relay", {}).get("replay_audit", [])]
    return {"sorties": sorted(sorties, key=lambda row: str(row.get("sortie_id"))),
            "coverage": sorted(coverage, key=lambda row: str(row.get("demand_id"))),
            "replay": sorted(replay, key=lambda row: str(row.get("trip_id")))}


def _core_objective(selected: dict[str, Any]) -> dict[str, Any]:
    objective = selected.get("objective", {})
    schedule = selected.get("schedule", {})
    relay = selected.get("relay", {})
    return {
        "WTD": objective.get("WTD", schedule.get("metrics", {}).get("WTD")),
        "transport_Cmax_s": objective.get("transport_Cmax_s", schedule.get("metrics", {}).get("Cmax_s")),
        "joint_Cmax_s": objective.get("joint_Cmax_s"),
        "transport_energy_kwh": objective.get("transport_energy_kwh"),
        "relay_energy_kwh": objective.get("relay_energy_kwh"),
        "total_energy_kwh": objective.get("total_energy_kwh"),
        "transport_n_trips": objective.get("transport_n_trips", schedule.get("metrics", {}).get("n_trips")),
        "relay_sorties": objective.get("relay_sorties", len(relay.get("relay_sorties", []))),
    }


def compare_q3_upstream(old_final: dict[str, Any], new_final: dict[str, Any], *, new_refreeze_head: str | None = None) -> dict[str, Any]:
    old_selected, new_selected = old_final["selected_solution"], new_final["selected_solution"]
    old_state, new_state = _selected_state(old_selected), _selected_state(new_selected)
    old_signature, new_signature = _hash(old_state), _hash(new_state)
    comparisons = {
        "transport_state": _compare(_transport_state(old_selected), _transport_state(new_selected)),
        "transport_schedule": _compare(_transport_schedule(old_selected), _transport_schedule(new_selected)),
        "relay_schedule": _compare(_relay_schedule(old_selected), _relay_schedule(new_selected)),
        "core_objective": _compare(_core_objective(old_selected), _core_objective(new_selected)),
    }
    selected_solution_equal = (old_selected.get("solution_id") == new_selected.get("solution_id") and
                               old_selected.get("operator") == new_selected.get("operator") and old_signature == new_signature)
    rows = {
        "old_q3_revision": old_final.get("metadata", {}).get("git_revision"),
        "new_q3_revision": new_final.get("metadata", {}).get("git_revision"),
        "q3_refreeze_head": new_refreeze_head,
        "old_q3_schema": old_final.get("metadata", {}).get("q3_final_schema"),
        "new_q3_schema": new_final.get("metadata", {}).get("q3_final_schema"),
        "selected_solution": {
            "old_solution_id": old_selected.get("solution_id"), "new_solution_id": new_selected.get("solution_id"),
            "old_operator": old_selected.get("operator"), "new_operator": new_selected.get("operator"),
            "old_recomputed_state_signature": old_signature,
            "new_recorded_state_signature": new_selected.get("state_signature"),
            "new_recomputed_state_signature": new_signature,
            "equal": selected_solution_equal,
        },
        "selected_solution_equal": selected_solution_equal,
        "transport_state_equal": not comparisons["transport_state"],
        "transport_schedule_equal": not comparisons["transport_schedule"],
        "relay_schedule_equal": not comparisons["relay_schedule"],
        "core_objective_equal": not comparisons["core_objective"],
        "tolerance_abs": TOLERANCE,
        "differences": comparisons,
        "candidate_pool_reuse_validated": False,
    }
    rows["semantic_equal"] = all((rows["selected_solution_equal"], rows["transport_state_equal"],
                                  rows["transport_schedule_equal"], rows["relay_schedule_equal"],
                                  rows["core_objective_equal"]))
    rows["candidate_pool_reuse_validated"] = rows["semantic_equal"]
    rows["status"] = "PASS" if rows["semantic_equal"] else "FAIL"
    return rows


def write_comparison(old_path: Path, new_path: Path, *, new_refreeze_head: str | None = None) -> dict[str, Any]:
    report = compare_q3_upstream(_load(old_path), _load(new_path), new_refreeze_head=new_refreeze_head)
    report.update({"old_q3_final_path": str(old_path), "new_q3_final_path": str(new_path),
                   "old_q3_final_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
                   "new_q3_final_sha256": hashlib.sha256(new_path.read_bytes()).hexdigest()})
    (results_root() / "q4_q3_upstream_refresh_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def write_comparison_from_git(old_ref: str, new_path: Path, *, new_refreeze_head: str | None = None) -> dict[str, Any]:
    """Compare against the Q4 branch's pre-refresh Q3 blob without rewriting it."""
    blob = subprocess.check_output(["git", "show", f"{old_ref}:implementation/q3/results/q3_final.json"])
    report = compare_q3_upstream(json.loads(blob.decode("utf-8")), _load(new_path), new_refreeze_head=new_refreeze_head)
    report.update({"old_q3_final_path": f"git:{old_ref}:implementation/q3/results/q3_final.json",
                   "new_q3_final_path": str(new_path),
                   "old_q3_final_sha256": hashlib.sha256(blob).hexdigest(),
                   "new_q3_final_sha256": hashlib.sha256(new_path.read_bytes()).hexdigest()})
    (results_root() / "q4_q3_upstream_refresh_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-q3-final", type=Path)
    parser.add_argument("--old-q3-git-ref")
    parser.add_argument("--new-q3-final", required=True, type=Path)
    parser.add_argument("--new-refreeze-head")
    args = parser.parse_args()
    if bool(args.old_q3_final) == bool(args.old_q3_git_ref):
        parser.error("provide exactly one of --old-q3-final or --old-q3-git-ref")
    report = (write_comparison(args.old_q3_final, args.new_q3_final, new_refreeze_head=args.new_refreeze_head)
              if args.old_q3_final else
              write_comparison_from_git(args.old_q3_git_ref, args.new_q3_final, new_refreeze_head=args.new_refreeze_head))
    print(json.dumps(report, ensure_ascii=False, indent=2))
