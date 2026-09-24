"""Bidirectional link budget and Direct/Relay/Outage communication logic."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

import math

from .terrain_los import LosEvaluation, evaluate_los

DIRECT = "DIRECT"
RELAY = "RELAY"
OUTAGE = "OUTAGE"


@dataclass(frozen=True)
class LinkEvaluation:
    available: bool
    path_loss_db: float
    loss_limit_db: float
    margin_db: float
    blocked: bool
    distance_m: float
    forward_loss_limit_db: float
    reverse_loss_limit_db: float
    los: LosEvaluation

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["los"] = self.los.as_dict()
        return out


@dataclass(frozen=True)
class CommunicationEvaluation:
    n_samples: int
    direct_samples: int
    relay_samples: int
    outage_samples: int
    outage_duration_s: float
    direct_fail_intervals: tuple[dict[str, Any], ...]
    min_link_margin_db: float
    communication_feasible: bool
    samples: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self, *, include_samples: bool = False) -> dict[str, Any]:
        out = asdict(self)
        if not include_samples:
            out.pop("samples", None)
        return out


def fspl_db(frequency_mhz: float, distance_m: float) -> float:
    """Free-space path loss, with MHz and km as required by the formula."""
    return 32.45 + 20.0 * math.log10(float(frequency_mhz)) + \
        20.0 * math.log10(max(float(distance_m) / 1000.0, 1e-9))


def directional_loss_limit_db(tx: Mapping[str, float], rx: Mapping[str, float],
                              comm: Mapping[str, Any]) -> float:
    return float(tx["Pt_dBm"]) + float(tx["Gt_dBi"]) + float(rx["Gt_dBi"]) - \
        float(comm["system_loss_db"]) - float(comm["threshold_dbm"])


def evaluate_bidirectional_link(point_a: tuple[float, float, float],
                                point_b: tuple[float, float, float],
                                interface_a: Mapping[str, float],
                                interface_b: Mapping[str, float],
                                comm: Mapping[str, Any], *, dem,
                                los_step_m: float = 10.0) -> LinkEvaluation:
    los = evaluate_los(point_a, point_b, dem=dem, step_m=los_step_m)
    forward = directional_loss_limit_db(interface_a, interface_b, comm)
    reverse = directional_loss_limit_db(interface_b, interface_a, comm)
    limit = min(forward, reverse)
    path_loss = fspl_db(float(comm["frequency_mhz"]), los.distance_m)
    if los.blocked:
        path_loss += float(comm["obstruction_loss_db"])
    margin = limit - path_loss
    return LinkEvaluation(available=bool(path_loss <= limit + 1e-12),
                          path_loss_db=float(path_loss), loss_limit_db=float(limit),
                          margin_db=float(margin), blocked=bool(los.blocked),
                          distance_m=float(los.distance_m),
                          forward_loss_limit_db=float(forward),
                          reverse_loss_limit_db=float(reverse), los=los)


def choose_communication_state(direct_available: bool, relay_available: bool) -> str:
    """Direct is always selected when available; a relay never overrides it."""
    if direct_available:
        return DIRECT
    return RELAY if relay_available else OUTAGE


def _gateway_point(nodes, comm: Mapping[str, Any]) -> tuple[float, float, float]:
    node = nodes.set_index("id").loc["O01"]
    return (float(node.lon), float(node.lat), float(node.elev) +
            float(comm["gateway_antenna_height_m"]))


def _service_covers(service: Mapping[str, Any], t_s: float) -> bool:
    return float(service["service_start_s"]) <= t_s <= float(service["service_end_s"])


def _relay_point(service: Mapping[str, Any]) -> tuple[float, float, float]:
    return (float(service["lon"]), float(service["lat"]), float(service["altitude_msl_m"]))


def evaluate_transport_communication(samples: Iterable[Mapping[str, Any]], *, comm: Mapping[str, Any],
                                     nodes, dem, dt_s: float,
                                     relay_services: Iterable[Mapping[str, Any]] | None = None,
                                     los_step_m: float = 10.0) -> CommunicationEvaluation:
    """Check continuous communication for every supplied trajectory sample.

    A relay service has no capacity field: one service may cover simultaneous
    transport UAVs when both physical links are available, matching the source
    data's absence of a channel-capacity constraint.
    """
    services = tuple(relay_services or ())
    gateway = _gateway_point(nodes, comm)
    records: list[dict[str, Any]] = []
    for sample in samples:
        point = (float(sample["x_lon"]), float(sample["y_lat"]), float(sample["z_m"]))
        direct = evaluate_bidirectional_link(point, gateway, comm["interfaces"]["U"],
                                              comm["interfaces"]["G01"], comm,
                                              dem=dem, los_step_m=los_step_m)
        selected_service = None
        relay_margin = float("-inf")
        if not direct.available:
            for service in services:
                if not _service_covers(service, float(sample["t_s"])):
                    continue
                rpoint = _relay_point(service)
                access = evaluate_bidirectional_link(point, rpoint, comm["interfaces"]["U"],
                                                      comm["interfaces"]["RA"], comm,
                                                      dem=dem, los_step_m=los_step_m)
                backhaul = evaluate_bidirectional_link(rpoint, gateway, comm["interfaces"]["RB"],
                                                        comm["interfaces"]["G01"], comm,
                                                        dem=dem, los_step_m=los_step_m)
                candidate_margin = min(access.margin_db, backhaul.margin_db)
                if access.available and backhaul.available and (
                        selected_service is None or candidate_margin > relay_margin):
                    selected_service = service
                    relay_margin = candidate_margin
        state = choose_communication_state(direct.available, selected_service is not None)
        margin = direct.margin_db if state in (DIRECT, OUTAGE) else relay_margin
        records.append({**dict(sample), "state": state,
                        "direct_available": bool(direct.available),
                        "direct_margin_db": float(direct.margin_db),
                        "relay_margin_db": None if not math.isfinite(relay_margin) else float(relay_margin),
                        "selected_relay_id": None if selected_service is None else selected_service.get("relay_id"),
                        "min_margin_db": float(margin) if math.isfinite(margin) else -1e9})
    if not records:
        raise ValueError("communication evaluator needs at least one trajectory sample")
    from .communication_intervals import extract_intervals
    direct_fail = extract_intervals(records, predicate=lambda r: not r["direct_available"], dt_s=dt_s)
    outages = extract_intervals(records, predicate=lambda r: r["state"] == OUTAGE, dt_s=dt_s)
    return CommunicationEvaluation(
        n_samples=len(records), direct_samples=sum(r["state"] == DIRECT for r in records),
        relay_samples=sum(r["state"] == RELAY for r in records),
        outage_samples=sum(r["state"] == OUTAGE for r in records),
        outage_duration_s=float(sum(x["duration_s"] for x in outages)),
        direct_fail_intervals=tuple(direct_fail),
        min_link_margin_db=float(min(r["min_margin_db"] for r in records)),
        communication_feasible=not any(r["state"] == OUTAGE for r in records),
        samples=tuple(records),
    )
