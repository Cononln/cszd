"""Q2 comparison-method interfaces.

The Q1 single-stop solution will be used as a baseline only after the common
Q2 route evaluator and schedule decoder are validated. It is not frozen as the
Q2 feasible region.
"""
from __future__ import annotations

from .models import Q2State


def q1_single_stop_baseline() -> Q2State:
    raise NotImplementedError("Q2-A only: baseline decoder starts after Q2-C")


def legacy_random_neighborhood_baseline() -> Q2State:
    raise NotImplementedError("Q2-A only: legacy baseline is comparison-only")
