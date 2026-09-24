"""Formal ALNS destroy operators (transport structure only)."""
from __future__ import annotations

import numpy as np

from .alns_solver import (_destroy_high_energy, _destroy_high_wtd, _destroy_random,
                          _destroy_related, _destroy_stop, _destroy_whole_route,
                          _remove_ids)
from .models import Q2State


def destroy_random_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    return _destroy_random(state, fraction, np.random.default_rng(seed))


def destroy_related_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    return _destroy_related(state, fraction, np.random.default_rng(seed))


def destroy_worst_route(state: Q2State, seed: int) -> Q2State:
    return _destroy_high_energy(state, 0.18, np.random.default_rng(seed))


def destroy_high_wtd(state: Q2State, seed: int) -> Q2State:
    # Standalone API lacks a schedule; callers in the formal loop pass it to
    # the schedule-aware implementation directly.
    return destroy_worst_route(state, seed)


def destroy_high_energy_route(state: Q2State, seed: int) -> Q2State:
    return _destroy_high_energy(state, 0.18, np.random.default_rng(seed))


def destroy_whole_route(state: Q2State, seed: int) -> Q2State:
    return _destroy_whole_route(state, np.random.default_rng(seed))


def destroy_stop(state: Q2State, seed: int) -> Q2State:
    return _destroy_stop(state, np.random.default_rng(seed))
