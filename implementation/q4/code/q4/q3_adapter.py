"""Read-only adapter from the formal Q3 selected solution to Q4."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


# The Q3 worktree is refrozen independently.  This commit identifies the
# immutable Q3 snapshot copied into this Q4 branch; it is provenance only and
# is never used to select a different Q3 solution.
Q3_REFREEZE_COMMIT = "35a5668e9822dc92c2d8c8a21bbd01f1452ba487"


def q4_root() -> Path:
    return Path(__file__).resolve().parents[2]


def results_root() -> Path:
    configured = os.environ.get("Q4_RESULTS_DIR")
    path = Path(configured).resolve() if configured else q4_root() / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def q3_final_path() -> Path:
    return q4_root().parents[0] / "q3" / "results" / "q3_final.json"


def q3_audit_path() -> Path:
    return q4_root().parents[0] / "q3" / "results" / "q3_final_audit.json"


def q3_freeze_report_path() -> Path:
    return q4_root().parents[0] / "q3" / "results" / "Q3_FREEZE_REPORT.md"


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def selected_solution_semantic_fingerprint(selected: dict[str, Any]) -> str:
    return _sha256({
        "solution_id": selected.get("solution_id"),
        "transport_state": selected.get("transport_state", {}),
        "schedule": selected.get("schedule", {}),
        "relay": selected.get("relay", {}),
        "objective": selected.get("objective", {}),
    })


def load_q3_selected_solution() -> dict[str, Any]:
    """Load exactly the selected Q3 solution, never Q3 candidate evidence."""
    final_path = q3_final_path()
    final = json.loads(final_path.read_text(encoding="utf-8"))
    selected = final.get("selected_solution")
    if not isinstance(selected, dict):
        raise ValueError("q3_final.json has no selected_solution")
    transport_state = selected.get("transport_state", {})
    schedule = selected.get("schedule", {})
    relay = selected.get("relay", {})
    interface = {
        "source_file": "implementation/q3/results/q3_final.json",
        "source_sha256": hashlib.sha256(final_path.read_bytes()).hexdigest(),
        "q3_git_revision": final.get("metadata", {}).get("git_revision"),
        "q3_final_schema": final.get("metadata", {}).get("q3_final_schema"),
        "q3_refreeze_commit": Q3_REFREEZE_COMMIT,
        "selected_solution_id": selected.get("solution_id"),
        "selected_solution_state_signature": selected.get("state_signature"),
        "selected_solution_fingerprint": selected_solution_semantic_fingerprint(selected),
        "transport_state": transport_state,
        "transport_schedule": schedule,
        "relay_schedule": relay,
        "fleet_configuration": selected.get("fleet_configuration", {}),
        "transport_assignments": [
            {key: record.get(key) for key in ("trip_id", "uid", "battery_id", "gtype", "start_time_s",
                                                "departure_time_s", "return_time_s", "charge_start_s", "charge_end_s")}
            for record in schedule.get("trip_records", [])
        ],
        "relay_assignments": [
            {key: sortie.get(key) for key in ("sortie_id", "relay_id", "energy_component_id", "launch_start_s",
                                               "service_start_s", "service_end_s", "return_end_s", "charge_start_s",
                                               "charge_end_s", "demand_ids")}
            for sortie in relay.get("relay_sorties", [])
        ],
        "delivery_times": [
            {"trip_id": record.get("trip_id"), "delivery_by_box_s": record.get("delivery_by_box_s", {})}
            for record in schedule.get("trip_records", [])
        ],
        "energy_components": {"transport": selected.get("objective", {}).get("transport_energy_kwh"),
                              "relay": selected.get("objective", {}).get("relay_energy_kwh"),
                              "total": selected.get("objective", {}).get("total_energy_kwh")},
        "completion_times_s": {"transport": selected.get("objective", {}).get("transport_Cmax_s"),
                               "joint": selected.get("objective", {}).get("joint_Cmax_s")},
        "communication": {"coverage_audit": relay.get("coverage_audit", []),
                          "replay_audit": relay.get("replay_audit", [])},
        "validator_checks": {
            "transport": selected.get("transport_validation", {}).get("checks", {}),
            "relay": selected.get("relay_validation", {}).get("checks", {}),
            "joint": selected.get("joint_validation", {}).get("checks", {}),
        },
        "q3_provenance": final.get("provenance", {}),
    }
    return interface
