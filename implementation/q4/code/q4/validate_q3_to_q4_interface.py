"""Independent Q3-to-Q4 formal interface gate."""
from __future__ import annotations

import json
from typing import Any

from .q3_adapter import load_q3_selected_solution, q3_audit_path, q3_final_path, results_root


def validate_interface(*, write: bool = True) -> dict[str, Any]:
    checks: dict[str, bool] = {"q3_final_exists": q3_final_path().exists(),
                               "q3_selected_solution_exists": False,
                               "q3_final_audit_pass": False,
                               "q3_joint_validator_pass": False,
                               "q3_zero_communication_outage": False,
                               "q3_all_hard_constraints_pass": False,
                               "q3_schedule_complete": False,
                               "q3_provenance_present": False}
    interface: dict[str, Any] | None = None
    audit: dict[str, Any] = {}
    if checks["q3_final_exists"]:
        try:
            interface = load_q3_selected_solution()
            checks["q3_selected_solution_exists"] = bool(interface.get("selected_solution_id"))
            trips = interface.get("transport_schedule", {}).get("trip_records", [])
            relay = interface.get("relay_schedule", {}).get("relay_sorties", [])
            checks["q3_schedule_complete"] = bool(trips) and bool(relay) and all(
                record.get("trip_id") and record.get("uid") and record.get("battery_id") for record in trips)
            joint = interface.get("validator_checks", {}).get("joint", {})
            checks["q3_joint_validator_pass"] = bool(joint) and all(joint.values())
            replay = interface.get("communication", {}).get("replay_audit", [])
            checks["q3_zero_communication_outage"] = bool(replay) and all(
                float(row.get("outage_duration_s", float("inf"))) == 0.0 and row.get("communication_feasible") is True
                for row in replay)
            validator_checks = interface.get("validator_checks", {})
            checks["q3_all_hard_constraints_pass"] = all(
                all(group.values()) for group in validator_checks.values() if group)
            checks["q3_provenance_present"] = bool(interface.get("q3_git_revision")) and bool(
                interface.get("q3_provenance", {}).get("formal_result_source"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            interface = None
    if q3_audit_path().exists():
        try:
            audit = json.loads(q3_audit_path().read_text(encoding="utf-8"))
            checks["q3_final_audit_pass"] = audit.get("status") == "PASS" and all(
                audit.get("checks", {}).values())
        except (OSError, json.JSONDecodeError):
            pass
    result = {"phase": "Q4-A Q3-to-Q4 interface", "status": "PASS" if all(checks.values()) else "FAIL",
              "checks": checks, "interface": interface, "q3_audit_status": audit.get("status")}
    if write:
        (results_root() / "q4_q3_interface_validation.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(validate_interface(), ensure_ascii=False, indent=2))
