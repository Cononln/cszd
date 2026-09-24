"""Q2-D adaptive-ALNS destroy-operator interfaces."""
from __future__ import annotations

from .models import Q2State


def destroy_random_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")


def destroy_related_boxes(state: Q2State, fraction: float, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")


def destroy_worst_route(state: Q2State, seed: int) -> Q2State:
    raise NotImplementedError("Q2-A only: ALNS operators start in Q2-D")
