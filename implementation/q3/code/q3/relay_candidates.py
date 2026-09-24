"""Coarse-to-filtered relay hover candidates for Q3-A."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np

from .communication import evaluate_bidirectional_link
from .relay_evaluator import evaluate_relay_candidate


def generate_relay_candidates(*, nodes, dem, comm: Mapping[str, Any],
                               relay_type: Mapping[str, Any],
                               spacing_m: float = 1500.0,
                               agl_levels_m: Iterable[float] = (60.0, 150.0, 300.0),
                               minimum_service_s: float = 60.0) -> list[dict[str, Any]]:
    """Generate a bounded DEM-grid candidate set and prune impossible points."""
    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    table = nodes.set_index("id")
    gateway = table.loc["O01"]
    # The grid is restricted to the operational node envelope, padded by one
    # grid spacing, rather than the whole DEM raster at 30 m resolution.
    lat0 = float(nodes["lat"].mean())
    lat_pad = spacing_m / 110574.0
    lon_pad = spacing_m / (111320.0 * np.cos(np.radians(lat0)))
    lons = np.arange(float(nodes["lon"].min()) - lon_pad,
                     float(nodes["lon"].max()) + lon_pad * 1.01, lon_pad)
    lats = np.arange(float(nodes["lat"].min()) - lat_pad,
                     float(nodes["lat"].max()) + lat_pad * 1.01, lat_pad)
    gateway_point = (float(gateway.lon), float(gateway.lat),
                     float(gateway.elev) + float(comm["gateway_antenna_height_m"]))
    levels = sorted({float(x) for x in agl_levels_m
                     if 0.0 <= float(x) <= float(relay_type["max_hover_agl_m"])})
    candidates = []
    for lon in lons:
        for lat in lats:
            if not dem.in_bounds(float(lon), float(lat)):
                continue
            ground = float(dem.elev(float(lon), float(lat)))
            for agl in levels:
                point = (float(lon), float(lat), ground + agl)
                backhaul = evaluate_bidirectional_link(point, gateway_point,
                                                        comm["interfaces"]["RB"],
                                                        comm["interfaces"]["G01"], comm,
                                                        dem=dem)
                if not backhaul.available:
                    continue
                relay_eval = evaluate_relay_candidate(float(lon), float(lat), agl,
                                                       (3600.0, 3600.0 + minimum_service_s),
                                                       relay_type=relay_type, nodes=nodes, dem=dem)
                if relay_eval.energy_margin_kwh < -1e-9:
                    continue
                candidates.append({"candidate_id": f"P{len(candidates)+1:04d}",
                                   "lon": float(lon), "lat": float(lat), "agl_m": agl,
                                   "altitude_msl_m": ground + agl,
                                   "gateway_link_margin_db": float(backhaul.margin_db),
                                   "gateway_los_blocked": bool(backhaul.blocked),
                                   "energy_margin_at_60s_kwh": float(relay_eval.energy_margin_kwh),
                                   "max_service_s": float(relay_eval.max_service_s)})
    return candidates


def assess_candidate_coverage(candidate: Mapping[str, Any], demand_samples: Iterable[Mapping[str, Any]],
                              *, comm: Mapping[str, Any], nodes, dem) -> dict[str, Any]:
    """Assess static-hover coverage of Direct-fail samples without scheduling it."""
    demand_samples = list(demand_samples)
    table = nodes.set_index("id")
    gateway = table.loc["O01"]
    rpoint = (float(candidate["lon"]), float(candidate["lat"]),
              float(candidate["altitude_msl_m"]))
    gpoint = (float(gateway.lon), float(gateway.lat),
              float(gateway.elev) + float(comm["gateway_antenna_height_m"]))
    backhaul = evaluate_bidirectional_link(rpoint, gpoint, comm["interfaces"]["RB"],
                                            comm["interfaces"]["G01"], comm, dem=dem)
    covered = []
    for row in demand_samples:
        upoint = (float(row["x_lon"]), float(row["y_lat"]), float(row["z_m"]))
        access = evaluate_bidirectional_link(upoint, rpoint, comm["interfaces"]["U"],
                                              comm["interfaces"]["RA"], comm, dem=dem)
        if access.available and backhaul.available:
            covered.append(row)
    return {"candidate_id": candidate["candidate_id"],
            "demand_samples": len(demand_samples),
            "covered_samples": len(covered),
            "coverage_ratio": len(covered) / max(1, len(demand_samples)),
            "backhaul_available": bool(backhaul.available),
            "backhaul_margin_db": float(backhaul.margin_db)}
