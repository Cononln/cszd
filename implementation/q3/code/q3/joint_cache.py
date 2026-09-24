"""Deterministic geometry and joint schedule caches."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze(v) for v in value)
    return value


def canonical_signature(value) -> str:
    """Stable SHA-256 signature; never use Python's process-randomised hash()."""
    payload = json.dumps(_freeze(value), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class JointCache:
    geometry: dict[Any, Any] = field(default_factory=dict)
    schedules: dict[Any, Any] = field(default_factory=dict)
    geometry_hits: int = 0
    geometry_misses: int = 0
    schedule_hits: int = 0
    schedule_misses: int = 0

    def geometry_key(self, route):
        return canonical_signature(route)

    def get_geometry(self, route):
        key = self.geometry_key(route)
        if key in self.geometry:
            self.geometry_hits += 1
            return self.geometry[key]
        self.geometry_misses += 1
        return None

    def put_geometry(self, route, value):
        self.geometry[self.geometry_key(route)] = value

    def schedule_key(self, route, start_time_s, uav_signature, battery_signature,
                     *, stop_sequence=None, trip_grouping=None, candidate_spacing_m=1500.0):
        return canonical_signature({"route": route, "start_time_s": round(float(start_time_s), 6),
                                    "uav_signature": uav_signature, "battery_signature": battery_signature,
                                    "stop_sequence": stop_sequence, "trip_grouping": trip_grouping,
                                    "candidate_spacing_m": float(candidate_spacing_m)})

    def get_schedule(self, route, start_time_s, uav_signature, battery_signature, **kwargs):
        key = self.schedule_key(route, start_time_s, uav_signature, battery_signature, **kwargs)
        if key in self.schedules:
            self.schedule_hits += 1
            return self.schedules[key]
        self.schedule_misses += 1
        return None

    def put_schedule(self, route, start_time_s, uav_signature, battery_signature, value, **kwargs):
        self.schedules[self.schedule_key(route, start_time_s, uav_signature, battery_signature, **kwargs)] = value
