"""Q2-D formal adaptive-ALNS solver interface.

The outer state will search transport structure only. UAV IDs, battery IDs and
times remain decoder variables as required by the Q2 modeling contract.
"""
from __future__ import annotations

from .models import Q2State


def solve_formal_q2(*, seed: int = 20260924, time_limit_s: float = 600.0) -> Q2State:
    raise NotImplementedError("Q2-A only: formal ALNS starts in Q2-D")
