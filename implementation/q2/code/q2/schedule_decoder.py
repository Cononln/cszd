"""Q2-C schedule-decoder interface.

The decoder will assign independent UAV and same-type shared-battery resources
for a fixed set of evaluated trips. It must model UAV NoOverlap, battery flight
plus recharge occupancy, and hard delivery deadlines. No schedule is generated
in Q2-A.
"""
from __future__ import annotations

from collections.abc import Sequence

from .models import Q2State, ScheduleAssignment


def decode_schedule(state: Q2State) -> Sequence[ScheduleAssignment]:
    raise NotImplementedError("Q2-A only: CP-SAT decoder starts in Q2-C")
