"""Q2-D adaptive-ALNS repair-operator interfaces."""
from __future__ import annotations

from .models import Q2State


def repair_cheapest_feasible(state: Q2State, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")


def repair_regret_k(state: Q2State, k: int, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")


def repair_deadline_first(state: Q2State, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")
