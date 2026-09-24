"""Q2-E independent event-simulation validator interface."""
from __future__ import annotations

from .models import Q2State


def validate_solution(state: Q2State) -> dict:
    """Return the future machine-readable validation contract."""
    raise NotImplementedError("Q2-A only: independent validator starts in Q2-E")
