"""Continuous 3-D transport trajectory sampling for Q3-A."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[4]
Q1_CODE = REPO_ROOT / "implementation" / "q1" / "code"
Q2_CODE = REPO_ROOT / "implementation" / "q2" / "code"
for path in (Q1_CODE, Q2_CODE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common.data import load_nodes, load_transport_types  # noqa: E402
from common.route import leg_geom  # noqa: E402
from q2.route_evaluator import evaluate_route_cached  # noqa: E402


def _route_key(route) -> tuple:
    return (route.gtype, tuple(route.stop_sequence),
            tuple((sid, tuple(route.boxes_by_stop[sid]))
                  for sid in route.stop_sequence))


def _times(duration_s: float, dt_s: float) -> list[float]:
    if duration_s <= 1e-10:
        return [0.0]
    n = int(math.floor(duration_s / dt_s))
    values = [min(duration_s, i * dt_s) for i in range(n + 1)]
    if values[-1] < duration_s - 1e-9:
        values.append(float(duration_s))
    return values


def _phase_samples(*, t0: float, duration_s: float, dt_s: float,
                   start: tuple[float, float, float],
                   end: tuple[float, float, float], phase: str,
                   segment: str, trip_id: str, gtype: str,
                   skip_first: bool) -> list[dict[str, Any]]:
    out = []
    for offset in _times(duration_s, dt_s):
        if skip_first and offset <= 1e-10:
            continue
        ratio = 0.0 if duration_s <= 1e-10 else offset / duration_s
        p = tuple(float(a + ratio * (b - a)) for a, b in zip(start, end))
        out.append({"trip_id": trip_id, "gtype": gtype,
                    "t_s": float(t0 + offset), "x_lon": p[0],
                    "y_lat": p[1], "z_m": p[2], "phase": phase,
                    "segment": segment})
    return out


def sample_transport_trajectory(route, *, start_time_s: float = 0.0,
                                dt_s: float = 2.0,
                                trip_id: str = "TRIP") -> list[dict[str, Any]]:
    """Sample climb, cruise, descent and each service interval continuously.

    ``start_time_s`` is the route-record start (before preparation).  Preparation
    and loading are intentionally omitted from communication samples; the
    first sample is at departure after Q2-B's preparation/loading duration.
    """
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    nodes = load_nodes().set_index("id")
    types = load_transport_types()
    ev = evaluate_route_cached(*_route_key(route))
    if not ev.route_feasible:
        raise ValueError("cannot sample an infeasible Q2 route")
    gt = types[route.gtype]
    t = float(start_time_s) + float(ev.prep_load_time_s)
    samples: list[dict[str, Any]] = []
    for leg_eval, a, b in zip(ev.legs, route.node_sequence[:-1],
                              route.node_sequence[1:]):
        geom = leg_geom(a, b)
        start_ops = (float(geom["lon_i"]), float(geom["lat_i"]),
                     float(geom["ops_i"]))
        cruise = (float(geom["lon_i"]), float(geom["lat_i"]),
                  float(geom["z_cruise"]))
        end_ops = (float(geom["lon_j"]), float(geom["lat_j"]),
                   float(geom["ops_j"]))
        segment = f"{a}->{b}"
        t_climb = float(geom["h_up"]) / float(gt["v_up"])
        t_cruise = float(geom["d"]) / float(gt["vc"])
        t_desc = float(geom["h_dn"]) / float(gt["v_down"])
        samples.extend(_phase_samples(t0=t, duration_s=t_climb, dt_s=dt_s,
                                      start=start_ops, end=cruise,
                                      phase="climb", segment=segment,
                                      trip_id=trip_id, gtype=route.gtype,
                                      skip_first=bool(samples)))
        t += t_climb
        # Cruise interpolates horizontally at constant z.
        cruise_end = (float(geom["lon_j"]), float(geom["lat_j"]),
                      float(geom["z_cruise"]))
        samples.extend(_phase_samples(t0=t, duration_s=t_cruise, dt_s=dt_s,
                                      start=cruise, end=cruise_end,
                                      phase="cruise", segment=segment,
                                      trip_id=trip_id, gtype=route.gtype,
                                      skip_first=bool(samples)))
        t += t_cruise
        samples.extend(_phase_samples(t0=t, duration_s=t_desc, dt_s=dt_s,
                                      start=cruise_end, end=end_ops,
                                      phase="descent", segment=segment,
                                      trip_id=trip_id, gtype=route.gtype,
                                      skip_first=bool(samples)))
        t += t_desc
        if b != "O01":
            service_s = float(ev.handover_time_by_sid[b])
            samples.extend(_phase_samples(
                t0=t, duration_s=service_s, dt_s=dt_s,
                start=end_ops, end=end_ops, phase="handover",
                segment=f"service:{b}", trip_id=trip_id,
                gtype=route.gtype, skip_first=bool(samples)))
            t += service_s
    if not samples:
        raise ValueError("route produced no trajectory samples")
    return samples


def trajectory_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    phases = {}
    for row in samples:
        phases[row["phase"]] = phases.get(row["phase"], 0) + 1
    return {"n_samples": len(samples), "t_start_s": samples[0]["t_s"],
            "t_end_s": samples[-1]["t_s"], "phases": phases,
            "segments": sorted({row["segment"] for row in samples})}
