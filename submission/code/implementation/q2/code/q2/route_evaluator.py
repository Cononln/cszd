# -*- coding: utf-8 -*-
"""Q2-B：多点路线物理评价器正式实现。

只计算一条多点路线自身的物理量（载荷逐站下降、逐段 leg_time /
leg_energy、多站交接累积、逐站送达偏移、可行性），不做 UAV 调度、
电池调度、绝对时刻、WTD、Cmax、ALNS。所有物理量均调用 Q1 common，
本模块不复制任何物理公式。
"""
from __future__ import annotations

import sys
from functools import lru_cache
from collections.abc import Mapping, Sequence
from pathlib import Path

Q2_DIR = Path(__file__).resolve().parents[2]
IMPL_DIR = Q2_DIR.parent
Q1_CODE = IMPL_DIR / "q1" / "code"
sys.path.insert(0, str(Q1_CODE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import load_boxes, load_transport_types  # noqa: E402
from common.route import leg_energy, leg_time  # noqa: E402

try:
    from .models import LegEvaluation, RouteEvaluation, RoutePlan
except ImportError:  # 直接按文件路径装载时的回退，与包内相对导入等价
    from models import LegEvaluation, RouteEvaluation, RoutePlan  # noqa: E402

ENERGY_TOL_KWH = 1e-9  # 与 Q1 正式能量比较容差一致


def make_route_plan(
    gtype: str,
    stop_sequence: Sequence[str],
    boxes_by_stop: Mapping[str, Sequence[str]],
) -> RoutePlan:
    """Normalize a candidate route without running physics or optimization."""
    stops = tuple(str(s) for s in stop_sequence)
    unknown_keys = set(boxes_by_stop) - set(stops)
    if unknown_keys:
        raise ValueError(f"boxes_by_stop has keys outside stop_sequence: {sorted(unknown_keys)}")
    missing_keys = set(stops) - set(boxes_by_stop)
    if missing_keys:
        raise ValueError(f"boxes_by_stop is missing stops: {sorted(missing_keys)}")
    grouped = {str(s): tuple(str(b) for b in boxes_by_stop[s]) for s in stops}
    return RoutePlan(gtype=gtype, stop_sequence=stops, boxes_by_stop=grouped)


def _validate_boxes(route: RoutePlan) -> dict[str, dict]:
    """真实货箱校验：存在性、box.sid 归属、每站非空。非法直接 raise。"""
    btab = load_boxes().set_index("box")
    info: dict[str, dict] = {}
    for sid in route.stop_sequence:
        pack = route.boxes_by_stop[sid]
        if len(pack) == 0:
            raise ValueError(f"stop {sid} carries no boxes")
        for b in pack:
            if b not in btab.index:
                raise ValueError(f"unknown box ID: {b}")
            if str(btab.loc[b, "sid"]) != sid:
                raise ValueError(
                    f"box {b} belongs to {btab.loc[b, 'sid']}, not {sid}")
            info[b] = {"mass": float(btab.loc[b, "mass"]),
                       "vol": float(btab.loc[b, "vol"])}
    return info


def evaluate_route(
    gtype: str,
    stop_sequence: Sequence[str],
    boxes_by_stop: Mapping[str, Sequence[str]],
) -> RouteEvaluation:
    """评价一条 O01 -> stops -> O01 多点路线（相对 start 的偏移口径）。"""
    route = make_route_plan(gtype, stop_sequence, boxes_by_stop)
    info = _validate_boxes(route)
    types = load_transport_types()
    if gtype not in types:
        raise ValueError(f"unknown transport type: {gtype}")
    gt = types[gtype]

    mass_by_stop = {s: sum(info[b]["mass"] for b in route.boxes_by_stop[s])
                    for s in route.stop_sequence}
    q0 = sum(mass_by_stop.values())
    v0 = sum(info[b]["vol"] for b in route.box_ids)
    mass_feasible = q0 <= float(gt["Q"]) + 1e-9
    volume_feasible = v0 <= float(gt["V"]) + 1e-12

    n_total = route.n_boxes
    prep_load = float(gt["t_prep"]) + n_total * float(gt["t_box_load"])
    hand_by_sid = {s: float(gt["t_hand_base"])
                   + len(route.boxes_by_stop[s]) * float(gt["t_hand_box"])
                   for s in route.stop_sequence}

    legs: list[LegEvaluation] = []
    delivery_offset_by_sid: dict[str, float] = {}
    payload_after: dict[str, float] = {}
    nodes = route.node_sequence
    remaining = q0
    t = prep_load
    e_total = 0.0
    for a, b in zip(nodes[:-1], nodes[1:]):
        tl = float(leg_time(gtype, a, b))
        en = float(leg_energy(gtype, a, b, remaining))
        legs.append(LegEvaluation(from_node=a, to_node=b,
                                  payload_kg=remaining, time_s=tl, energy_kwh=en))
        t += tl
        e_total += en
        if b != "O01":
            t += hand_by_sid[b]
            delivery_offset_by_sid[b] = t
            remaining -= mass_by_stop[b]
            payload_after[b] = remaining

    energy_limit = (1 - float(gt["rho"])) * float(gt["Euse"])
    energy_feasible = e_total <= energy_limit + ENERGY_TOL_KWH
    route_duration = t
    return RouteEvaluation(
        route=route, legs=tuple(legs),
        delivery_offset_by_sid=delivery_offset_by_sid,
        payload_after_stop_by_sid=payload_after,
        initial_payload_kg=q0, initial_volume_m3=v0,
        total_route_energy_kwh=e_total, energy_limit_kwh=energy_limit,
        energy_margin_kwh=energy_limit - e_total,
        prep_load_time_s=prep_load, handover_time_by_sid=hand_by_sid,
        route_duration_s=route_duration,
        mass_limit_kg=float(gt["Q"]), volume_limit_m3=float(gt["V"]),
        mass_feasible=mass_feasible, volume_feasible=volume_feasible,
        energy_feasible=energy_feasible,
        route_feasible=mass_feasible and volume_feasible and energy_feasible,
    )


@lru_cache(maxsize=20000)
def evaluate_route_cached(
    gtype: str,
    stop_sequence: tuple[str, ...],
    boxes_by_stop: tuple[tuple[str, tuple[str, ...]], ...],
) -> RouteEvaluation:
    """Memoized Q2-B evaluation for ALNS candidates.

    The cache key is canonical and contains the exact box IDs, so this is only
    memoization of the formal evaluator (never an approximation).  A fresh
    mapping is reconstructed on every cache miss; callers must treat returned
    mappings as read-only.
    """
    grouped = {sid: tuple(boxes) for sid, boxes in boxes_by_stop}
    return evaluate_route(gtype, stop_sequence, grouped)


def route_cache_info() -> dict[str, int]:
    info = evaluate_route_cached.cache_info()
    return {"hits": int(info.hits), "misses": int(info.misses),
            "maxsize": int(info.maxsize or 0), "currsize": int(info.currsize)}
