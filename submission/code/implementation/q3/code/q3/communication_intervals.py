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


def validate_blind_intervals(samples: list[Mapping[str, Any]],
                             intervals: list[Mapping[str, Any]], *, dt_s: float,
                             tolerance_s: float | None = None) -> dict[str, Any]:
    """Independently check a Direct-failure interval export.

    This intentionally does *not* call :func:`extract_intervals`.  It derives
    contiguous Direct-failure runs directly from the labelled samples and then
    checks that the exported intervals cover exactly those samples, have valid
    temporal order and preserve each run's spatial/altitude envelope.
    """
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    ordered = sorted((dict(r) for r in samples), key=lambda r: float(r["t_s"]))
    if not ordered:
        raise ValueError("blind-interval validator needs at least one sample")
    tolerance = float(dt_s if tolerance_s is None else tolerance_s)
    expected: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in ordered:
        failed = not bool(row["direct_available"])
        contiguous = current and float(row["t_s"]) - float(current[-1]["t_s"]) <= 1.5 * dt_s + 1e-9
        if failed and (not current or contiguous):
            current.append(row)
        else:
            if current:
                expected.append(current)
            current = [row] if failed else []
    if current:
        expected.append(current)

    normalized = [dict(r) for r in intervals]
    ordered_ok = all(float(row["start_s"]) <= float(row["end_s"]) + 1e-9
                     for row in normalized)
    sorted_ok = all(float(right["start_s"]) >= float(left["start_s"]) - 1e-9
                    for left, right in zip(normalized, normalized[1:]))
    nonoverlap_ok = all(float(right["start_s"]) > float(left["end_s"]) + 1e-9
                        for left, right in zip(normalized, normalized[1:]))

    def contained(row: Mapping[str, Any]) -> list[dict[str, Any]]:
        t = float(row["t_s"])
        return [interval for interval in normalized
                if float(interval["start_s"]) - 1e-9 <= t <= float(interval["end_s"]) + 1e-9]

    fail_samples = [row for run in expected for row in run]
    covered_fail = [row for row in fail_samples if contained(row)]
    falsely_included = [row for row in ordered
                         if bool(row["direct_available"]) and contained(row)]

    envelope_ok = True
    for interval in normalized:
        members = [row for row in fail_samples
                   if float(interval["start_s"]) - 1e-9 <= float(row["t_s"]) <= float(interval["end_s"]) + 1e-9]
        if not members:
            envelope_ok = False
            continue
        envelope_ok = envelope_ok and all(
            float(interval["lon_min"]) - 1e-9 <= float(row["x_lon"]) <= float(interval["lon_max"]) + 1e-9 and
            float(interval["lat_min"]) - 1e-9 <= float(row["y_lat"]) <= float(interval["lat_max"]) + 1e-9 and
            float(interval["alt_min_m"]) - 1e-9 <= float(row["z_m"]) <= float(interval["alt_max_m"]) + 1e-9
            for row in members)

    duration_intervals = float(sum(float(row["duration_s"]) for row in normalized))
    # Derive the sample-side support independently from the sample timestamps.
    # A trajectory phase may start a fraction of ``dt`` after the preceding
    # phase; counting ``n * dt`` would then falsely accumulate those sub-step
    # offsets.  Each run covers its observed span plus one terminal sample bin.
    duration_samples = float(sum((float(run[-1]["t_s"]) - float(run[0]["t_s"]) + dt_s)
                                 for run in expected if run))
    duration_error = duration_intervals - duration_samples
    passed = bool(
        ordered_ok and sorted_ok and nonoverlap_ok and
        len(covered_fail) == len(fail_samples) and not falsely_included and
        len(normalized) == len(expected) and envelope_ok and
        abs(duration_error) <= tolerance + 1e-9
    )
    return {
        "trip_id": str(ordered[0].get("trip_id", "")),
        "dt_s": float(dt_s),
        "fail_sample_count": len(fail_samples),
        "covered_fail_sample_count": len(covered_fail),
        "false_included_pass_samples": len(falsely_included),
        "interval_count": len(normalized),
        "expected_interval_count": len(expected),
        "duration_from_intervals_s": duration_intervals,
        "duration_from_samples_s": duration_samples,
        "duration_error_s": duration_error,
        "duration_tolerance_s": tolerance,
        "ordered": ordered_ok,
        "sorted": sorted_ok,
        "non_overlapping": nonoverlap_ok,
        "envelope_coverage": envelope_ok,
        "pass": passed,
    }
