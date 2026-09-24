"""Independent Q3-C joint validation contract."""
from __future__ import annotations

from typing import Any, Mapping


JOINT_CHECK_KEYS = (
    "all_boxes_once", "hard_deadlines", "mass", "volume", "transport_reserve",
    "transport_uav_overlap", "battery_overlap", "battery_soc_recharge",
    "relay_uav_overlap", "energy_component_overlap", "relay_reserve",
    "relay_charge", "arrival_timing", "full_communication",
)


def _explicit_checks(transport_validation: Mapping[str, Any]) -> dict[str, bool]:
    supplied = transport_validation.get("checks", transport_validation)
    aliases = {
        "all_boxes_once": ("all_boxes_once", "all_boxes_delivered_once", "missing_boxes", "duplicate_boxes", "no_split_boxes"),
        "hard_deadlines": ("hard_deadlines", "first_deadlines_pass", "medical_deadlines_pass"),
        "mass": ("mass", "mass_pass"), "volume": ("volume", "volume_pass"),
        "transport_reserve": ("transport_reserve", "return_reserve_pass"),
        "transport_uav_overlap": ("transport_uav_overlap", "uav_overlap_zero"),
        "battery_overlap": ("battery_overlap", "battery_overlap_zero"),
        "battery_soc_recharge": ("battery_soc_recharge", "soc_pass", "charge_pass", "charge_before_reuse_pass"),
    }
    transport_keys = set(aliases)
    out = {}
    for key in JOINT_CHECK_KEYS:
        if key not in transport_keys:
            continue
        values = [bool(supplied[name]) for name in aliases[key] if name in supplied]
        out[key] = bool(values) and all(values)
    return out


def _relay_checks(relay_result, *, reserve_rho: float = 0.2) -> dict[str, bool]:
    status = relay_result.get("baseline_status") if isinstance(relay_result, Mapping) else getattr(relay_result, "baseline_status", None)
    checks = relay_result.get("checks", {}) if isinstance(relay_result, Mapping) else getattr(relay_result, "checks", {})
    sorties = relay_result.get("sorties", ()) if isinstance(relay_result, Mapping) else getattr(relay_result, "sorties", ())
    relay_audit = {"relay_uav_overlap": True, "energy_component_overlap": True,
                   "relay_reserve": True, "relay_charge": True, "arrival_timing": True,
                   "full_communication": True}
    relay_groups, component_groups = {}, {}
    for sortie in sorties:
        get = (lambda key, default=None: sortie.get(key, default)) if isinstance(sortie, Mapping) else (lambda key, default=None: getattr(sortie, key, default))
        relay_groups.setdefault(get("relay_id"), []).append((float(get("launch_start_s")), float(get("resource_end_s"))))
        component_groups.setdefault(get("energy_component_id"), []).append((float(get("launch_start_s")), float(get("charge_end_s"))))
        relay_audit["relay_reserve"] &= float(get("soc_after", 0.0)) >= float(reserve_rho) - 1e-9
        relay_audit["relay_charge"] &= float(get("charge_end_s", 0.0)) >= float(get("resource_end_s", 0.0))
        relay_audit["arrival_timing"] &= float(get("relay_ready_s", 0.0)) <= float(get("service_start_s", 0.0)) + 1e-7
    def no_overlap(groups):
        return all(all(b[0] >= a[1] - 1e-7 for a, b in zip(sorted(intervals), sorted(intervals)[1:]))
                   for intervals in groups.values())
    relay_audit["relay_uav_overlap"] = no_overlap(relay_groups)
    relay_audit["energy_component_overlap"] = no_overlap(component_groups)
    replay = relay_result.get("replay_audit", ()) if isinstance(relay_result, Mapping) else getattr(relay_result, "replay_audit", ())
    relay_audit["full_communication"] = bool(replay) and all(
        bool(row.get("communication_feasible", False)) and int(row.get("outage_samples", 1)) == 0 for row in replay)
    return {key: bool(value) for key, value in relay_audit.items()}


def validate_joint_candidate(transport_validation: Mapping[str, Any], relay_result, *, reserve_rho: float = 0.2) -> dict[str, Any]:
    """Recompute the formal hard-gate schema without trusting solver flags."""
    checks = _explicit_checks(transport_validation)
    checks.update(_relay_checks(relay_result, reserve_rho=reserve_rho))
    relay_status = relay_result.get("baseline_status") if isinstance(relay_result, Mapping) else getattr(relay_result, "baseline_status", None)
    if relay_status == "UNRESOLVED":
        return {"status": "UNRESOLVED", "checks": checks, "reason": "relay_decode_unresolved"}
    if relay_status != "FEASIBLE":
        return {"status": "INFEASIBLE_PROVEN", "checks": checks,
                "reason": "relay_baseline_not_feasible"}
    return {"status": "PASS" if all(checks.values()) else "INFEASIBLE_PROVEN", "checks": checks,
            "reason": None if all(checks.values()) else "joint_hard_constraint_failure"}


def validate_q3_joint(transport_validation: dict, relay_result, *, communication_audit: dict | None = None) -> dict:
    """Short-circuit infeasible transport or relay stages as hard constraints."""
    transport_ok = transport_validation.get("status") in {"PASS", "FEASIBLE"}
    relay_status = relay_result.get("status") if isinstance(relay_result, dict) else getattr(relay_result, "status", None)
    relay_ok = relay_status == "PASS"
    relay_unresolved = relay_status == "UNRESOLVED"
    comm_ok = True if communication_audit is None else bool(communication_audit.get("communication_feasible", False))
    checks = {"transport": transport_ok, "relay": relay_ok, "communication": comm_ok,
              "all_boxes_once": transport_ok, "hard_deadlines": transport_ok,
              "transport_uav_overlap": transport_ok, "battery_overlap": transport_ok,
              "transport_energy": transport_ok, "relay_uav_overlap": relay_ok,
              "energy_component_overlap": relay_ok, "relay_reserve": relay_ok,
              "relay_charge": relay_ok, "full_communication": comm_ok}
    if relay_unresolved:
        return {"status": "UNRESOLVED", "checks": checks, "reason": "relay_decode_unresolved",
                "relay_decode_unresolved": True}
    return {"status": "PASS" if all(checks.values()) else "INFEASIBLE_PROVEN", "checks": checks,
            "reason": None if all(checks.values()) else "hard_constraint_failure",
            "relay_decode_unresolved": False}
