"""Formal ALNS repair operators."""
from __future__ import annotations

import numpy as np

from .alns_solver import _repair
from .models import Q2State


def repair_cheapest_feasible(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="cheapest-delta")


def repair_regret_k(state: Q2State, k: int, seed: int) -> Q2State:
    if k != 2:
        raise ValueError("formal Q2 implements regret-2")
    return _repair(state, np.random.default_rng(seed), mode="regret-2")


def repair_deadline_first(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="deadline-first")


def repair_energy_aware(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="energy-aware")


def repair_new_trip(state: Q2State, seed: int) -> Q2State:
    return _repair(state, np.random.default_rng(seed), mode="new-trip")
