"""Q3-C immutable state and result contracts; no formal solver is run here."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Q3State:
    transport_state: Any


@dataclass(frozen=True)
class JointMetrics:
    WTD: float
    joint_Cmax_s: float
    transport_energy_kwh: float
    relay_energy_kwh: float
    total_energy_kwh: float
    transport_n_trips: int
    relay_n_sorties: int

    def as_dict(self) -> dict[str, Any]:
        return {"WTD": self.WTD, "joint_Cmax_s": self.joint_Cmax_s,
                "transport_energy_kwh": self.transport_energy_kwh,
                "relay_energy_kwh": self.relay_energy_kwh,
                "total_energy_kwh": self.total_energy_kwh,
                "transport_n_trips": self.transport_n_trips,
                "relay_n_sorties": self.relay_n_sorties}


@dataclass(frozen=True)
class JointEvaluation:
    feasible: bool
    metrics: JointMetrics | None = None
    reason: str | None = None
    checks: Mapping[str, bool] = field(default_factory=dict)
