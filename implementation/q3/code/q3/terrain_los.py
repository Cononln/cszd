"""Terrain-aware line-of-sight evaluation for Q3-A."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class LosEvaluation:
    blocked: bool
    min_clearance_m: float
    critical_location: dict[str, float] | None
    distance_m: float
    n_terrain_samples: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_los(p0: tuple[float, float, float], p1: tuple[float, float, float],
                 *, dem, step_m: float = 10.0, endpoint_buffer_m: float = 30.0) -> LosEvaluation:
    """Evaluate terrain clearance along a full 3-D link, not just endpoints.

    Coordinates are ``(longitude, latitude, altitude_msl_m)``.  Sampling at
    or immediately beside an endpoint is excluded to avoid treating an antenna
    located on its supporting terrain pixel as an obstruction.
    """
    lon0, lat0, z0 = map(float, p0)
    lon1, lat1, z1 = map(float, p1)
    if not dem.in_bounds(lon0, lat0) or not dem.in_bounds(lon1, lat1):
        raise ValueError("LOS endpoint lies outside DEM coverage")
    s, lons, lats, terrain = dem.profile(lon0, lat0, lon1, lat1, step_m=step_m)
    total = float(s[-1])
    if total <= 1e-9:
        return LosEvaluation(False, float("inf"), None, 0.0, int(len(s)))
    mask = (s > min(endpoint_buffer_m, total / 2.0)) & \
           (s < total - min(endpoint_buffer_m, total / 2.0))
    if not np.any(mask):
        return LosEvaluation(False, float("inf"), None, total, int(len(s)))
    s_i = np.asarray(s)[mask]
    terrain_i = np.asarray(terrain)[mask]
    line_i = z0 + (z1 - z0) * (s_i / total)
    clearance = line_i - terrain_i
    critical = int(np.nanargmin(clearance))
    loc = {"lon": float(np.asarray(lons)[mask][critical]),
           "lat": float(np.asarray(lats)[mask][critical]),
           "terrain_m": float(terrain_i[critical]),
           "line_altitude_m": float(line_i[critical]),
           "distance_from_start_m": float(s_i[critical])}
    return LosEvaluation(bool(clearance[critical] < 0.0), float(clearance[critical]),
                         loc, total, int(len(s)))
