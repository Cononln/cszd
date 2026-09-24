"""Q2-D stop-order local-search interface."""
from __future__ import annotations

from .models import Q2State


def improve_stop_order(state: Q2State, seed: int) -> Q2State:
    """Reserved for 2-opt, relocate, swap and reversal neighborhoods."""
    raise NotImplementedError("Q2-A only: route-order search starts in Q2-D")
