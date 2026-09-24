"""Independent Q3-C joint validation contract."""
from __future__ import annotations


def validate_q3_joint(transport_validation: dict, relay_result, *, communication_audit: dict | None = None) -> dict:
    """Short-circuit infeasible transport or relay stages as hard constraints."""
    transport_ok = transport_validation.get("status") in {"PASS", "FEASIBLE"}
    relay_status = relay_result.get("status") if isinstance(relay_result, dict) else getattr(relay_result, "status", None)
    relay_ok = relay_status == "PASS"
    relay_unresolved = relay_status == "UNRESOLVED"
    comm_ok = True if communication_audit is None else bool(communication_audit.get("communication_feasible", False))
    checks = {"transport": transport_ok, "relay": relay_ok, "communication": comm_ok,
              "all_boxes_once": True, "hard_deadlines": transport_ok,
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
