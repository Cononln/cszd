"""Q3-C objective arithmetic and fixed normalization contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .joint_models import JointMetrics

METRIC_KEYS = ("WTD", "joint_Cmax_s", "total_energy_kwh", "transport_n_trips", "relay_n_sorties")


def _point(candidate):
    """Return the minimisation objective point for a mapping or JointMetrics."""
    return {key: float(candidate[key] if isinstance(candidate, Mapping) else getattr(candidate, key))
            for key in METRIC_KEYS}


def dominates(a, b) -> bool:
    """True when *a* is no worse in every objective and strictly better in one."""
    pa, pb = _point(a), _point(b)
    return all(pa[key] <= pb[key] + 1e-12 for key in METRIC_KEYS) and any(
        pa[key] < pb[key] - 1e-12 for key in METRIC_KEYS)


def nondominated_filter(candidates):
    """Stable Pareto filter; duplicate/equal points are retained once."""
    kept = []
    seen = set()
    for candidate in candidates:
        point = tuple(_point(candidate)[key] for key in METRIC_KEYS)
        if point in seen:
            continue
        if any(dominates(other, candidate) for other in candidates if other is not candidate):
            continue
        kept.append(candidate)
        seen.add(point)
    return kept


def pareto_ideal_nadir(candidates):
    """Compute final-archive ideal/nadir values, independently of search anchors."""
    points = [_point(candidate) for candidate in candidates]
    if not points:
        raise ValueError("cannot normalize an empty Pareto archive")
    return ({key: min(point[key] for point in points) for key in METRIC_KEYS},
            {key: max(point[key] for point in points) for key in METRIC_KEYS})


def select_representative(candidates, *, weights=None):
    """Select a deterministic compromise using final Pareto ideal/nadir."""
    if not candidates:
        raise ValueError("cannot select from an empty Pareto archive")
    ideal, nadir = pareto_ideal_nadir(candidates)
    weights = dict(weights or {key: 1.0 for key in METRIC_KEYS})
    def score(candidate):
        point = _point(candidate)
        values = [(point[key] - ideal[key]) / max(1e-12, nadir[key] - ideal[key]) for key in METRIC_KEYS]
        return (max(weights[key] * values[index] for index, key in enumerate(METRIC_KEYS)),
                sum(weights[key] * values[index] for index, key in enumerate(METRIC_KEYS)),
                tuple(point[key] for key in METRIC_KEYS))
    return min(candidates, key=score)


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
