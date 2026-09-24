"""Route-order local search neighborhoods used by Q2-D."""
from __future__ import annotations

from .alns_solver import _local_stop_search, evaluate_state
from .models import Q2State


def improve_stop_order(state: Q2State, seed: int) -> Q2State:
    schedule = evaluate_state(state, cp_workers=1, decoder_time_limit_s=3.0, seed=seed)
    if schedule is None:
        return state
    improved, _ = _local_stop_search(state, schedule, cp_workers=1, seed=seed,
                                     decoder_time_limit_s=3.0)
    return improved
