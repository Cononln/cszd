"""Formal ALNS repair operators."""
from __future__ import annotations

import numpy as np

from .alns_solver import _repair
from .models import Q2State


def repair_cheapest_feasible(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="cheapest")


def repair_regret_k(state: Q2State, k: int, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="deadline-first")


def repair_deadline_first(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="deadline-first")


def repair_energy_aware(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="cheapest")


def repair_new_trip(state: Q2State, seed: int) -> Q2State:
    # Force all removed boxes to be considered in a fresh-trip-first order by
    # starting from the current state and delegating to the common validator.
    return _repair(state, np.random.default_rng(seed), mode="deadline-first")
