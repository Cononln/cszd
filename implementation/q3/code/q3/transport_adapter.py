"""Formal adapters from Q2 transport state/schedule contracts to Q3-B input."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
Q2_CODE = HERE.parents[3] / "q2" / "code"
if str(Q2_CODE) not in sys.path:
    sys.path.insert(0, str(Q2_CODE))

from q2.schedule_decoder import decode_schedule  # noqa: E402
from q2.validate_q2 import validate_solution  # noqa: E402


def decode_transport_candidate(transport_state, *, cp_workers: int = 1,
                               time_limit_s: float = 60.0, seed: int = 0):
    """Run Q2's sole formal transport decoder and independent replay validator."""
    schedule = decode_schedule(transport_state, cp_workers=cp_workers,
                               time_limit_s=time_limit_s, fixed_seed=seed)
    validation = validate_solution(transport_state, schedule)
    return schedule, validation


def relay_decoder_contract(transport_state, schedule) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build the serializable Q3-B input without copying any Q2 physics."""
    routes = []
    for index, trip in enumerate(transport_state.trips, 1):
        record = schedule.assignments[index - 1]
        routes.append({"trip_id": str(record.trip_id), "route": trip})
    timeline = [{"trip_id": str(assignment.trip_id), "start_time_s": float(assignment.start_time_s)}
                for assignment in schedule.assignments]
    return {"routes": routes}, timeline


def transport_signature(transport_state, schedule) -> dict[str, Any]:
    """Only structural and timing values that can alter communication/relay decoding."""
    routes = []
    for index, trip in enumerate(transport_state.trips, 1):
        assignment = schedule.assignments[index - 1]
        routes.append({"trip_id": str(assignment.trip_id), "gtype": trip.gtype,
                       "stops": tuple(trip.stop_sequence),
                       "boxes_by_stop": {str(k): tuple(v) for k, v in trip.boxes_by_stop.items()},
                       "uid": str(assignment.uid), "battery_id": str(assignment.battery_id),
                       "start_time_s": float(assignment.start_time_s)})
    return {"routes": routes}
