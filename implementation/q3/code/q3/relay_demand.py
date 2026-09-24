"""Construction of Q3-B relay demand intervals from transport trajectories."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping

import pandas as pd

from .communication import evaluate_transport_communication
from .data_q3 import load_q3_inputs
from .trajectory import sample_transport_trajectory
from .audit_q3_a import _q2_tables, _route_from_results


@dataclass(frozen=True)
class RelayDemandInterval:
    demand_id: str
    transport_trip_id: str
    gtype: str
    start_s: float
    end_s: float
    duration_s: float
    trajectory_samples: tuple[Mapping[str, Any], ...]
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    alt_min: float
    alt_max: float

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["trajectory_samples"] = list(self.trajectory_samples)
        return out


def _schedule_start(transport_schedule: Any, trip_id: str) -> float:
    if transport_schedule is None:
        return 0.0
    if isinstance(transport_schedule, pd.DataFrame):
        rows = transport_schedule.loc[transport_schedule["trip_id"].astype(str) == str(trip_id)]
        return float(rows.iloc[0].get("start_time_s", rows.iloc[0].get("departure_time_s", 0.0))) if not rows.empty else 0.0
    if isinstance(transport_schedule, Mapping):
        value = transport_schedule.get(trip_id, transport_schedule.get(str(trip_id), 0.0))
        return float(value.get("start_time_s", value.get("departure_time_s", 0.0)) if isinstance(value, Mapping) else value)
    for row in transport_schedule:
        if str(row.get("trip_id")) == str(trip_id):
            return float(row.get("start_time_s", row.get("departure_time_s", 0.0)))
    return 0.0


def build_relay_demands(*, transport_state=None, transport_schedule=None, dt_s: float = 2.0,
                        inputs: dict[str, Any] | None = None, dem=None) -> tuple[list[RelayDemandInterval], list[dict[str, Any]]]:
    """Return every Direct-fail interval and its trajectory samples.

    The baseline path reads the current Q2 formal CSVs.  A caller may instead
    provide an iterable of ``RoutePlan`` objects as ``transport_state`` and a
    schedule mapping with ``start_time_s`` values.
    """
    inputs = inputs or load_q3_inputs()
    if transport_state is None:
        trips, stops, boxes = _q2_tables()
        # Q2 formal is an integration baseline only. Its recorded start times
        # determine temporal overlap here; arbitrary caller states remain free
        # to supply their own schedule through the public API.
        transport_schedule = trips if transport_schedule is None else transport_schedule
        routes = [(str(row.trip_id), _route_from_results(str(row.trip_id), trips, stops, boxes))
                  for row in trips.itertuples(index=False)]
    else:
        routes = []
        if isinstance(transport_state, Mapping):
            iterable = transport_state.get("routes", transport_state.get("trips", ()))
        else:
            iterable = transport_state
        for index, route in enumerate(iterable, 1):
            trip_id = str(getattr(route, "trip_id", None) or (route.get("trip_id") if isinstance(route, Mapping) else f"TRIP-{index:03d}"))
            route_obj = route.get("route", route) if isinstance(route, Mapping) else route
            routes.append((trip_id, route_obj))
    demands: list[RelayDemandInterval] = []
    audit: list[dict[str, Any]] = []
    for trip_id, route in routes:
        start = _schedule_start(transport_schedule, trip_id)
        samples = sample_transport_trajectory(route, start_time_s=start, trip_id=trip_id, dt_s=dt_s)
        evaluation = evaluate_transport_communication(samples, comm=inputs["communication"],
                                                       nodes=inputs["nodes"], dem=dem, dt_s=dt_s)
        for index, interval in enumerate(evaluation.direct_fail_intervals, 1):
            members = tuple(row for row in evaluation.samples
                            if float(interval["start_s"]) - 1e-9 <= float(row["t_s"]) <= float(interval["end_s"]) + 1e-9)
            demand_id = f"D-{trip_id}-{index:02d}"
            demand = RelayDemandInterval(
                demand_id=demand_id, transport_trip_id=trip_id, gtype=route.gtype,
                start_s=float(interval["start_s"]), end_s=float(interval["end_s"]),
                duration_s=float(interval["duration_s"]), trajectory_samples=members,
                lon_min=float(interval["lon_min"]), lon_max=float(interval["lon_max"]),
                lat_min=float(interval["lat_min"]), lat_max=float(interval["lat_max"]),
                alt_min=float(interval["alt_min_m"]), alt_max=float(interval["alt_max_m"]),
            )
            demands.append(demand)
            audit.append({"demand_id": demand_id, "transport_trip_id": trip_id, "dt_s": dt_s,
                          "start_s": demand.start_s, "end_s": demand.end_s,
                          "duration_s": demand.duration_s, "sample_count": len(members),
                          "direct_fail": True})
    return demands, audit
