"""Strict relay-candidate coverage matrix construction."""
from __future__ import annotations

from typing import Any, Mapping

from .communication import evaluate_bidirectional_link


def build_coverage_matrix(demands, candidates, *, inputs, dem, endpoint_buffer_m: float = 30.0):
    table = inputs["nodes"].set_index("id")
    gateway = table.loc["O01"]
    gpoint = (float(gateway.lon), float(gateway.lat),
              float(gateway.elev) + float(inputs["communication"]["gateway_antenna_height_m"]))
    rows: list[dict[str, Any]] = []
    matrix: dict[str, set[str]] = {str(c["candidate_id"]): set() for c in candidates}
    for candidate in candidates:
        cid = str(candidate["candidate_id"])
        rpoint = (float(candidate["lon"]), float(candidate["lat"]), float(candidate["altitude_msl_m"]))
        backhaul = evaluate_bidirectional_link(rpoint, gpoint, inputs["communication"]["interfaces"]["RB"],
                                               inputs["communication"]["interfaces"]["G01"],
                                               inputs["communication"], dem=dem,
                                               endpoint_buffer_m=endpoint_buffer_m)
        for demand in demands:
            failed_sample = None
            for sample in demand.trajectory_samples:
                upoint = (float(sample["x_lon"]), float(sample["y_lat"]), float(sample["z_m"]))
                access = evaluate_bidirectional_link(upoint, rpoint, inputs["communication"]["interfaces"]["U"],
                                                     inputs["communication"]["interfaces"]["RA"],
                                                     inputs["communication"], dem=dem,
                                                     endpoint_buffer_m=endpoint_buffer_m)
                if not (access.available and backhaul.available):
                    failed_sample = sample
                    break
            covered = failed_sample is None and bool(demand.trajectory_samples) and bool(backhaul.available)
            if covered:
                matrix[cid].add(str(demand.demand_id))
            rows.append({"candidate_id": cid, "demand_id": demand.demand_id,
                         "covered": covered, "sample_count": len(demand.trajectory_samples),
                         "failed_sample_t_s": None if failed_sample is None else float(failed_sample["t_s"]),
                         "backhaul_available": bool(backhaul.available),
                         "backhaul_margin_db": float(backhaul.margin_db)})
    return matrix, rows


def strict_replay_coverage(demand, candidate, *, inputs, dem, endpoint_buffer_m: float = 30.0) -> bool:
    """Independent all-sample replay used by validators."""
    table = inputs["nodes"].set_index("id")
    gateway = table.loc["O01"]
    gpoint = (float(gateway.lon), float(gateway.lat), float(gateway.elev) + float(inputs["communication"]["gateway_antenna_height_m"]))
    rpoint = (float(candidate["lon"]), float(candidate["lat"]), float(candidate["altitude_msl_m"]))
    backhaul = evaluate_bidirectional_link(rpoint, gpoint, inputs["communication"]["interfaces"]["RB"],
                                           inputs["communication"]["interfaces"]["G01"], inputs["communication"],
                                           dem=dem, endpoint_buffer_m=endpoint_buffer_m)
    if not backhaul.available:
        return False
    return all(evaluate_bidirectional_link(
        (float(row["x_lon"]), float(row["y_lat"]), float(row["z_m"])), rpoint,
        inputs["communication"]["interfaces"]["U"], inputs["communication"]["interfaces"]["RA"],
        inputs["communication"], dem=dem, endpoint_buffer_m=endpoint_buffer_m).available
        for row in demand.trajectory_samples)
