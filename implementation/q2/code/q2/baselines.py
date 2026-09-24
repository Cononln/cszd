"""Comparison structures evaluated by the common Q2-B/C/E chain."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .alns_solver import _destroy_random, _repair, build_initial_state
from .models import Q2State, RoutePlan


def q2_single_stop_baseline(seed: int = 20260924) -> Q2State:
    """Q2 data / Q2 decoder single-service-area packing baseline."""
    return build_initial_state(seed)


def q1_formal_structure() -> Q2State:
    """Read, never rebuild, the frozen Q1 18-trip structure for comparison."""
    q2_dir = Path(__file__).resolve().parents[2]
    q1_results = q2_dir.parent / "q1" / "results"
    trips = pd.read_csv(q1_results / "q1_solution_trips.csv")
    boxes = pd.read_csv(q1_results / "q1_solution_boxes.csv")
    route_plans = []
    for trip in trips.itertuples(index=False):
        trip_id, gtype, sid = str(trip.trip_id), str(trip.gtype), str(trip.sid)
        packed = tuple(boxes.loc[boxes["trip_id"].astype(str) == trip_id, "box"].astype(str))
        route_plans.append(RoutePlan(gtype, (sid,), {sid: packed}))
    return Q2State(tuple(route_plans))


def legacy_random_neighborhood_baseline(seed: int = 20260924) -> Q2State:
    """Legacy-style random perturbation, re-evaluated only by formal Q2 logic."""
    rng = np.random.default_rng(seed)
    state = build_initial_state(seed)
    partial = _destroy_random(state, 0.15, rng)
    return _repair(partial, rng, mode="cheapest-delta")
