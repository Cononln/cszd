"""Fixed multi-objective normalization for one Q2 formal run.

The ideal/nadir bounds are assembled before the ALNS seeds start and are never
updated during the search.  They are therefore valid both for Tchebycheff
acceptance and for selecting one transparent representative from the global
Pareto archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

METRIC_KEYS = ("WTD", "Cmax_s", "total_energy_kwh", "n_trips")


@dataclass(frozen=True)
class Normalization:
    ideal: Mapping[str, float]
    nadir: Mapping[str, float]
    rho: float = 0.005

    @classmethod
    def from_metrics(cls, metrics_rows: Sequence[Mapping[str, float]], *, rho: float = 0.005):
        if not metrics_rows:
            raise ValueError("normalization needs at least one anchor metric row")
        ideal = {k: min(float(row[k]) for row in metrics_rows) for k in METRIC_KEYS}
        nadir = {k: max(float(row[k]) for row in metrics_rows) for k in METRIC_KEYS}
        # A nonzero denominator preserves all four objectives when anchors
        # happen to tie on an indicator.
        for key in METRIC_KEYS:
            if nadir[key] - ideal[key] <= 1e-9:
                nadir[key] = ideal[key] + max(1.0, abs(ideal[key]) * 0.05)
        return cls(ideal=ideal, nadir=nadir, rho=float(rho))

    def normalized(self, metrics: Mapping[str, float]) -> dict[str, float]:
        return {key: (float(metrics[key]) - float(self.ideal[key])) /
                (float(self.nadir[key]) - float(self.ideal[key])) for key in METRIC_KEYS}

    def scalar(self, metrics: Mapping[str, float], weights: Mapping[str, float]) -> float:
        values = self.normalized(metrics)
        weighted = [float(weights[key]) * values[key] for key in METRIC_KEYS]
        return max(weighted) + self.rho * sum(weighted)

    def ideal_distance(self, metrics: Mapping[str, float]) -> float:
        values = self.normalized(metrics)
        return sum(values[key] ** 2 for key in METRIC_KEYS) ** 0.5

    def as_dict(self) -> dict:
        return {"ideal": dict(self.ideal), "nadir": dict(self.nadir), "rho": self.rho}
