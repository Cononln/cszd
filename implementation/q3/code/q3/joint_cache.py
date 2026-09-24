"""Deterministic geometry and joint schedule caches."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _freeze(value):
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass
class JointCache:
    geometry: dict[Any, Any] = field(default_factory=dict)
    schedules: dict[Any, Any] = field(default_factory=dict)

    def geometry_key(self, route):
        return _freeze(route)

    def schedule_key(self, route, start_time_s, uav_signature, battery_signature):
        return (_freeze(route), round(float(start_time_s), 6), _freeze(uav_signature), _freeze(battery_signature))

    def get_schedule(self, route, start_time_s, uav_signature, battery_signature):
        return self.schedules.get(self.schedule_key(route, start_time_s, uav_signature, battery_signature))

    def put_schedule(self, route, start_time_s, uav_signature, battery_signature, value):
        self.schedules[self.schedule_key(route, start_time_s, uav_signature, battery_signature)] = value
