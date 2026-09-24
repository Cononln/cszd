"""Independent file-based validator for the persisted C2 feasible seed."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import transport_adapter as _transport_adapter  # register Q2 code root
from q2.models import Q2State, RoutePlan, ScheduleAssignment, ScheduleResult
from q2.validate_q2 import validate_solution

from .joint_validator import validate_joint_candidate
from .relay_decoder_protocol import Q3BRelayDecoderAdapter
from .transport_adapter import relay_decoder_contract
from .validate_q3_b import validate_q3_b


def _results_root() -> Path:
    configured = os.environ.get("Q3_RESULTS_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2] / "results"


def _state(payload: dict[str, Any]) -> Q2State:
    trips = []
    for row in payload["transport_state"]["trips"]:
        trips.append(RoutePlan(str(row["gtype"]), tuple(row["stop_sequence"]),
                               {str(key): tuple(value) for key, value in row["boxes_by_stop"].items()}))
    return Q2State(tuple(trips))


def _schedule(payload: dict[str, Any]) -> ScheduleResult:
    data = payload["schedule"]
    assignments = tuple(ScheduleAssignment(str(row["trip_id"]), str(row["uid"]),
                                            str(row["battery_id"]), float(row["start_time_s"]))
                        for row in data["assignments"])
    return ScheduleResult(str(data["status"]), assignments=assignments,
                          trip_records=tuple(data["trip_records"]), metrics=dict(data["metrics"]),
                          checks=dict(data["checks"]), solver_status=str(data["solver_status"]),
                          stage_statuses=dict(data["stage_statuses"]))


def validate_q3_c2(seed_path: Path | None = None) -> dict[str, Any]:
    path = seed_path or (_results_root() / "q3_c2_feasible_seed.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "selected_solution" in payload:
        payload = {"status": "PASS", **payload["selected_solution"]}
    state, schedule = _state(payload), _schedule(payload)
    transport = validate_solution(state, schedule)
    relay_state, relay_schedule = relay_decoder_contract(state, schedule)
    relay = Q3BRelayDecoderAdapter().decode_relay_schedule(relay_state, relay_schedule,
                                                            candidate_spacing_m=1500.0)
    relay_validation = validate_q3_b(relay, transport_state=relay_state, transport_schedule=relay_schedule)
    joint = validate_joint_candidate(transport, relay)
    checks = {
        "seed_declares_pass": payload.get("status") == "PASS",
        "q2_transport_replay_pass": transport.get("status") == "PASS",
        "q3b_real_decoder_pass": relay.decoder_status == "PASS" and relay.baseline_status == "FEASIBLE",
        "q3b_independent_validator_pass": relay_validation.get("decoder_validation_status") == "PASS" and
                                             all(relay_validation.get("checks", {}).values()),
        "joint_independent_validator_pass": joint.get("status") == "PASS" and all(joint.get("checks", {}).values()),
        "zero_communication_outage": all(row.get("outage_duration_s") == 0.0 and row.get("outage_samples") == 0
                                           for row in relay_validation.get("full_replay_audit", [])),
    }
    return {"phase": "Q3-C-C2-independent-validation", "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks, "transport": transport, "relay": {"decoder_status": relay.decoder_status,
            "baseline_status": relay.baseline_status, "solver_status": relay.solver_status,
            "metrics": relay.metrics}, "relay_validation": relay_validation, "joint": joint}


if __name__ == "__main__":
    print(json.dumps(validate_q3_c2(), ensure_ascii=False, indent=2))
