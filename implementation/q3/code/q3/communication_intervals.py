"""Extraction of temporal communication-demand intervals."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def extract_intervals(samples: list[Mapping[str, Any]], *, predicate: Callable[[Mapping[str, Any]], bool],
                      dt_s: float) -> list[dict[str, Any]]:
    """Merge consecutive qualifying samples into auditable time intervals."""
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    rows = sorted(samples, key=lambda row: float(row["t_s"]))
    intervals: list[dict[str, Any]] = []
    current: list[Mapping[str, Any]] = []
    for row in rows:
        qualifies = bool(predicate(row))
        contiguous = current and float(row["t_s"]) - float(current[-1]["t_s"]) <= 1.5 * dt_s + 1e-9
        if qualifies and (not current or contiguous):
            current.append(row)
        else:
            if current:
                intervals.append(_summarise(current, dt_s))
            current = [row] if qualifies else []
    if current:
        intervals.append(_summarise(current, dt_s))
    return intervals


def _summarise(rows: list[Mapping[str, Any]], dt_s: float) -> dict[str, Any]:
    start, end = float(rows[0]["t_s"]), float(rows[-1]["t_s"])
    return {
        "trip_id": str(rows[0].get("trip_id", "")),
        "segment_first": str(rows[0].get("segment", "")),
        "segment_last": str(rows[-1].get("segment", "")),
        "start_s": start,
        "end_s": end,
        "duration_s": max(float(dt_s), end - start + float(dt_s)),
        "n_samples": len(rows),
        "lon_min": min(float(r["x_lon"]) for r in rows),
        "lon_max": max(float(r["x_lon"]) for r in rows),
        "lat_min": min(float(r["y_lat"]) for r in rows),
        "lat_max": max(float(r["y_lat"]) for r in rows),
        "alt_min_m": min(float(r["z_m"]) for r in rows),
        "alt_max_m": max(float(r["z_m"]) for r in rows),
        "sample_times_s": [float(r["t_s"]) for r in rows],
    }
