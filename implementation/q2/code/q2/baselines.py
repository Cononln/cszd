"""Comparison structures evaluated through the same Q2-B/C chain."""
from __future__ import annotations

import numpy as np

from .alns_solver import _destroy_random, _repair, build_initial_state
from .models import Q2State


def q1_single_stop_baseline(seed: int = 20260924) -> Q2State:
    """Single-service-area structure (packing is only for capacity feasibility)."""
    return build_initial_state(seed)


def legacy_random_neighborhood_baseline(seed: int = 20260924) -> Q2State:
    """Reproduce the legacy random-neighborhood idea with the formal evaluator."""
    rng = np.random.default_rng(seed)
    state = build_initial_state(seed)
    partial = _destroy_random(state, 0.15, rng)
    return _repair(partial, rng, mode="cheapest")
