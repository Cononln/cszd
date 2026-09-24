"""Q2 的领域对象和跨阶段数据契约。

这里只描述运输结构，不在对象中复制 Q1 的物理公式。路线的停靠序列不含
O01；正式路线解释为 ``O01 -> stop_sequence -> O01``。后续阶段负责把该
结构交给 Q1 common 的航段接口和资源调度器。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RoutePlan:
    """一个多点运输架次的结构。

    ``boxes_by_stop`` 的键必须与 ``stop_sequence`` 完全一致；每个货箱 ID
    在一条路线内最多出现一次，但跨路线的全局覆盖由独立 validator 检查。
    """

    gtype: str
    stop_sequence: tuple[str, ...]
    boxes_by_stop: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if self.gtype not in {"A", "B", "C"}:
            raise ValueError(f"unsupported transport type: {self.gtype}")
        stops = tuple(self.stop_sequence)
        if not stops:
            raise ValueError("a Q2 route must visit at least one service area")
        if len(set(stops)) != len(stops):
            raise ValueError("a Q2 route cannot visit one service area twice")
        if "O01" in stops:
            raise ValueError("stop_sequence excludes depot O01")
        if set(self.boxes_by_stop) != set(stops):
            raise ValueError("boxes_by_stop keys must equal stop_sequence")
        if any(not self.boxes_by_stop[sid] for sid in stops):
            raise ValueError("each service-area stop must deliver at least one box")
        box_ids = [box for sid in stops for box in self.boxes_by_stop[sid]]
        if len(box_ids) != len(set(box_ids)):
            raise ValueError("a route contains a duplicate box ID")

    @property
    def node_sequence(self) -> tuple[str, ...]:
        """Closed node sequence used by the multi-stop evaluator."""
        return ("O01", *self.stop_sequence, "O01")

    @property
    def box_ids(self) -> tuple[str, ...]:
        return tuple(box for sid in self.stop_sequence for box in self.boxes_by_stop[sid])

    @property
    def n_boxes(self) -> int:
        return len(self.box_ids)


@dataclass(frozen=True)
class ScheduleAssignment:
    """Resource assignment returned by the Q2-C schedule decoder."""

    trip_id: str
    uid: str
    battery_id: str
    start_time_s: float


@dataclass(frozen=True)
class Q2State:
    """ALNS state: only transport structure belongs in the outer chromosome."""

    trips: tuple[RoutePlan, ...] = field(default_factory=tuple)

    @property
    def box_ids(self) -> tuple[str, ...]:
        return tuple(box for trip in self.trips for box in trip.box_ids)


@dataclass(frozen=True)
class LegEvaluation:
    """Contract for one directed leg; values are populated in Q2-B."""

    from_node: str
    to_node: str
    payload_kg: float
    time_s: float
    energy_kwh: float


@dataclass(frozen=True)
class RouteEvaluation:
    """Contract returned by the Q2-B route evaluator.

    The defaults represent an unevaluated object, not a feasible route. A later
    implementation must populate every numerical field and all feasibility flags.
    """

    route: RoutePlan
    legs: tuple[LegEvaluation, ...] = field(default_factory=tuple)
    delivery_offset_by_sid: Mapping[str, float] = field(default_factory=dict)
    initial_payload_kg: float | None = None
    initial_volume_m3: float | None = None
    total_route_energy_kwh: float | None = None
    energy_limit_kwh: float | None = None
    energy_margin_kwh: float | None = None
    prep_load_time_s: float | None = None
    handover_time_by_sid: Mapping[str, float] = field(default_factory=dict)
    route_duration_s: float | None = None
    mass_limit_kg: float | None = None
    volume_limit_m3: float | None = None
    payload_after_stop_by_sid: Mapping[str, float] = field(default_factory=dict)

    mass_feasible: bool | None = None
    volume_feasible: bool | None = None
    energy_feasible: bool | None = None
    route_feasible: bool | None = None
