"""Q2-B route-evaluator contract.

Q2-A deliberately does not evaluate a formal route. The implementation in Q2-B
must call ``common.route.leg_time`` and ``common.route.leg_energy`` for every
directed leg, update payload after each stop, and include the preceding stop's
handover time in every later delivery offset.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import RouteEvaluation, RoutePlan


def make_route_plan(
    gtype: str,
    stop_sequence: Sequence[str],
    boxes_by_stop: Mapping[str, Sequence[str]],
) -> RoutePlan:
    """Normalize a candidate route without running physics or optimization."""
    stops = tuple(str(s) for s in stop_sequence)
    grouped = {str(s): tuple(str(b) for b in boxes_by_stop[s]) for s in stops}
    return RoutePlan(gtype=gtype, stop_sequence=stops, boxes_by_stop=grouped)


def evaluate_route(
    gtype: str,
    stop_sequence: Sequence[str],
    boxes_by_stop: Mapping[str, Sequence[str]],
) -> RouteEvaluation:
    """Q2-B interface; intentionally unavailable during Q2-A."""
    route = make_route_plan(gtype, stop_sequence, boxes_by_stop)
    raise NotImplementedError(
        "Q2-A only: multi-stop physics is implemented and validated in Q2-B"
    )
