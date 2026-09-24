"""Q3-C objective arithmetic and fixed normalization contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .joint_models import JointMetrics

METRIC_KEYS = ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")


def joint_metrics(transport_metrics: Mapping[str, float], relay_metrics: Mapping[str, float]) -> JointMetrics:
    transport_cmax = float(transport_metrics.get("Cmax_s", transport_metrics.get("return_time_s", 0.0)))
    relay_cmax = float(relay_metrics.get("relay_cmax_s", relay_metrics.get("Cmax_s", 0.0)))
    transport_energy = float(transport_metrics.get("total_energy_kwh", 0.0))
    relay_energy = float(relay_metrics.get("relay_energy_kwh", 0.0))
    return JointMetrics(WTD=float(transport_metrics.get("WTD", 0.0)),
                        joint_Cmax_s=max(transport_cmax, relay_cmax),
                        transport_energy_kwh=transport_energy,
                        relay_energy_kwh=relay_energy,
                        total_energy_kwh=transport_energy + relay_energy,
                        transport_n_trips=int(transport_metrics.get("n_trips", 0)),
                        relay_n_sorties=int(relay_metrics.get("relay_sortie_count", 0)))


@dataclass(frozen=True)
class FixedNormalization:
    ideal: Mapping[str, float]
    nadir: Mapping[str, float]
    rho: float = 0.005

    def normalized(self, metrics: Mapping[str, float]) -> dict[str, float]:
        return {key: (float(metrics[key]) - float(self.ideal[key])) /
                max(1e-12, float(self.nadir[key]) - float(self.ideal[key])) for key in METRIC_KEYS}

    def tchebycheff(self, metrics: Mapping[str, float], weights: Mapping[str, float]) -> float:
        values = self.normalized(metrics)
        weighted = [float(weights[key]) * values[key] for key in METRIC_KEYS]
        return max(weighted) + self.rho * sum(weighted)
