"""Relay sortie, reserve and shared-energy-component evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[4]
Q1_CODE = REPO_ROOT / "implementation" / "q1" / "code"
if str(Q1_CODE) not in sys.path:
    sys.path.insert(0, str(Q1_CODE))

from common.dem import get_dem  # noqa: E402
from common.config import G, KWH_J  # noqa: E402
from common.physics import (charge_time, max_relay_service_time, relay_leg,
                            relay_mission_energy, relay_mission_time)  # noqa: E402


@dataclass(frozen=True)
class RelayEvaluation:
    feasible: bool
    lon: float
    lat: float
    agl_m: float
    altitude_msl_m: float
    service_start_s: float
    service_end_s: float
    relay_ready_s: float
    launch_start_s: float
    return_end_s: float
    resource_end_s: float
    out_leg: Mapping[str, float]
    back_leg: Mapping[str, float]
    flight_energy_kwh: float
    service_energy_kwh: float
    total_energy_kwh: float
    reserve_limit_kwh: float
    energy_margin_kwh: float
    soc_after: float
    charge_time_s: float
    max_service_s: float
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _physics_type(rt: Mapping[str, Any]) -> dict[str, Any]:
    """Map descriptive Q3 audit names to the Q1 common relay API."""
    aliases = {
        "m_takeoff": "m_takeoff_kg", "vc": "cruise_speed_mps",
        "p_cruise": "cruise_power_kw", "Euse": "Euse_kwh",
        "rho": "reserve_rho", "t_prep": "prep_time_s",
        "t_link": "link_setup_s", "t_turn": "turnaround_s",
        "v_up": "climb_speed_mps", "v_down": "descent_speed_mps",
        "eta_up": "climb_efficiency", "eta_down": "descent_efficiency",
        "p_hover": "hover_power_kw", "p_comm": "communication_power_kw",
    }
    out = dict(rt)
    for target, source in aliases.items():
        if target not in out:
            out[target] = out[source]
    return out


def _adjust_for_high_hover(leg: Mapping[str, float], *, hover_altitude_m: float,
                           rt: Mapping[str, Any], outbound: bool) -> dict[str, float]:
    """Append the required vertical motion if AGL hover lies above cruise.

    ``common.physics.relay_leg`` supplies the Q1/Q2 terrain-clear cruise leg.
    A Q3 hover point can legally lie higher than that cruise altitude, so this
    small extension adds only the necessary local vertical climb/descent using
    the same Q1 mass, efficiency and unit conversion convention.
    """
    out = dict(leg)
    extra = max(0.0, float(hover_altitude_m) - float(out["z_cruise"]))
    if outbound:
        out["t"] = float(out["t"]) + extra / float(rt["v_up"])
        extra_energy = float(rt["m_takeoff"]) * G * extra / float(rt["eta_up"]) / KWH_J
        out["e_up"] = float(out["e_up"]) + extra_energy
        out["e"] = float(out["e"]) + extra_energy
    else:
        out["t"] = float(out["t"]) + extra / float(rt["v_down"])
    out["extra_hover_vertical_m"] = extra
    return out


def evaluate_relay_candidate(x: float, y: float, agl_m: float,
                             service_interval: tuple[float, float],
                             *, relay_type: Mapping[str, Any], nodes,
                             dem=None) -> RelayEvaluation:
    """Evaluate a single allowed O01 -> P -> O01 fixed-hover sortie."""
    dem = dem or get_dem()
    rt = _physics_type(relay_type)
    start_s, end_s = map(float, service_interval)
    if end_s < start_s:
        raise ValueError("relay service interval end precedes start")
    if not dem.in_bounds(float(x), float(y)):
        raise ValueError("relay candidate lies outside DEM coverage")
    if agl_m < 0 or agl_m > float(rt["max_hover_agl_m"]) + 1e-9:
        raise ValueError("relay candidate AGL violates official maximum")
    node = nodes.set_index("id").loc["O01"]
    ground = float(dem.elev(float(x), float(y)))
    altitude = ground + float(agl_m)
    out = _adjust_for_high_hover(
        relay_leg("O01", "P", float(node.lon), float(node.lat), float(x), float(y),
                  float(node.elev), altitude, rt, dem=dem),
        hover_altitude_m=altitude, rt=rt, outbound=True)
    back = _adjust_for_high_hover(
        relay_leg("P", "O01", float(x), float(y), float(node.lon), float(node.lat),
                  altitude, float(node.elev), rt, dem=dem),
        hover_altitude_m=altitude, rt=rt, outbound=False)
    service_s = end_s - start_s
    total_energy, service_energy = relay_mission_energy(rt, out, back, service_s)
    reserve_limit = (1.0 - float(rt["reserve_rho"])) * float(rt["Euse_kwh"])
    margin = reserve_limit - total_energy
    ready = start_s  # construction below guarantees link setup ends at service start
    launch = ready - float(rt["t_link"]) - float(out["t"]) - float(rt["t_prep"])
    return_end = end_s + float(back["t"])
    resource_end = return_end + float(rt["t_turn"])
    soc = 1.0 - total_energy / float(rt["Euse"])
    max_service = max_relay_service_time(rt, out, back)
    reason = None
    if launch < -1e-9:
        reason = "requires_pre_horizon_launch"
    elif margin < -1e-9:
        reason = "reserve_violation"
    return RelayEvaluation(
        feasible=reason is None, lon=float(x), lat=float(y), agl_m=float(agl_m),
        altitude_msl_m=altitude, service_start_s=start_s, service_end_s=end_s,
        relay_ready_s=ready, launch_start_s=launch, return_end_s=return_end,
        resource_end_s=resource_end, out_leg=out, back_leg=back,
        flight_energy_kwh=float(out["e"] + back["e"]),
        service_energy_kwh=float(service_energy), total_energy_kwh=float(total_energy),
        reserve_limit_kwh=float(reserve_limit), energy_margin_kwh=float(margin),
        soc_after=float(soc),
        charge_time_s=float(charge_time(float(relay_type["energy_t_full_s"]), max(0.0, soc))),
        max_service_s=float(max_service), reason=reason,
    )


def validate_relay_resource_schedule(sorties: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit UAV and energy-component non-overlap, including charging.

    There is intentionally no capacity/charger constraint: the official data
    supplies only reusable energy components, not charging piles or relay
    channel counts.
    """
    rows = [dict(row) for row in sorties]
    def no_overlap(intervals):
        ordered = sorted(intervals)
        return all(right[0] >= left[1] - 1e-9 for left, right in zip(ordered, ordered[1:]))
    by_uav: dict[str, list[tuple[float, float]]] = {}
    by_component: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        by_uav.setdefault(str(row["relay_id"]), []).append((float(row["launch_start_s"]),
                                                               float(row["resource_end_s"])))
        by_component.setdefault(str(row["energy_component_id"]), []).append(
            (float(row["launch_start_s"]), float(row["charge_end_s"])))
    return {"relay_uav_overlap_zero": all(no_overlap(v) for v in by_uav.values()),
            "energy_component_overlap_zero": all(no_overlap(v) for v in by_component.values()),
            "n_sorties": len(rows)}
