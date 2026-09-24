"""Formal ALNS destroy operators (transport structure only)."""
from __future__ import annotations

import numpy as np

from .alns_solver import _destroy_random, _destroy_related, _destroy_worst, _remove_ids
from .models import Q2State


def destroy_random_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    return _destroy_random(state, fraction, np.random.default_rng(seed))


def destroy_related_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    return _destroy_related(state, fraction, np.random.default_rng(seed))


def destroy_worst_route(state: Q2State, seed: int) -> Q2State:
    return _destroy_worst(state, 0.18, np.random.default_rng(seed))


def destroy_high_wtd(state: Q2State, seed: int) -> Q2State:
    return _destroy_worst(state, 0.12, np.random.default_rng(seed))


def destroy_high_energy_route(state: Q2State, seed: int) -> Q2State:
    return _destroy_worst(state, 0.18, np.random.default_rng(seed))


def destroy_whole_route(state: Q2State, seed: int) -> Q2State:
    rng = np.random.default_rng(seed)
    if not state.trips:
        return state
    trip = state.trips[int(rng.integers(0, len(state.trips)))]
    return _remove_ids(state, set(trip.box_ids))


def destroy_stop(state: Q2State, seed: int) -> Q2State:
    rng = np.random.default_rng(seed)
    stops = [s for t in state.trips for s in t.stop_sequence]
    if not stops:
        return state
    sid = stops[int(rng.integers(0, len(stops)))]
    return _remove_ids(state, {b for t in state.trips for s in t.stop_sequence
                               if s == sid for b in t.boxes_by_stop[s]})
