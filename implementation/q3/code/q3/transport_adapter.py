"""Formal adapters from Q2 transport state/schedule contracts to Q3-B input."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
Q2_CODE = HERE.parents[3] / "q2" / "code"
if str(Q2_CODE) not in sys.path:
    sys.path.insert(0, str(Q2_CODE))

from q2.schedule_decoder import decode_schedule  # noqa: E402
from q2.models import Q2State, RoutePlan  # noqa: E402
from q2.validate_q2 import validate_solution  # noqa: E402

# Q2 results live beside ``q3`` under the repository's ``implementation``
# directory.  Keep this adapter read-only and resolve the path from the
# repository layout rather than from the current working directory.
RESULTS = HERE.parents[3] / "q2" / "results"


def _trip_number(value: str) -> int:
    return int(str(value).replace("T", ""))


def load_q2_formal_state() -> Q2State:
    """Reconstruct Q2's published formal route structure as a read-only state.

    CSV timelines are intentionally *not* used as a Q3 transport schedule;
    C1 must feed this state back through the Q2 decoder and validator.
    """
    trips_path = RESULTS / "q2_solution_trips.csv"
    boxes_path = RESULTS / "q2_solution_boxes.csv"
    with trips_path.open("r", encoding="utf-8-sig", newline="") as handle:
        trip_rows = sorted(csv.DictReader(handle), key=lambda row: _trip_number(row["trip_id"]))
    with boxes_path.open("r", encoding="utf-8-sig", newline="") as handle:
        box_rows = list(csv.DictReader(handle))
    by_trip: dict[str, dict[str, list[str]]] = {}
    for row in box_rows:
        by_trip.setdefault(str(row["trip_id"]), {}).setdefault(str(row["sid"]), []).append(str(row["box"]))
    routes = []
    for row in trip_rows:
        trip_id = str(row["trip_id"])
        stops = tuple(json.loads(row["stop_sequence"]))
        boxes_by_stop = {sid: tuple(by_trip.get(trip_id, {}).get(sid, ())) for sid in stops}
        routes.append(RoutePlan(gtype=str(row["gtype"]), stop_sequence=stops, boxes_by_stop=boxes_by_stop))
    state = Q2State(tuple(routes))
    if len(state.trips) != len(trip_rows) or len(set(state.box_ids)) != len(state.box_ids):
        raise ValueError("Q2 formal CSV reconstruction failed uniqueness checks")
    return state


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
