"""Independent Q3-C joint validation contract."""
from __future__ import annotations


def validate_q3_joint(transport_validation: dict, relay_result, *, communication_audit: dict | None = None) -> dict:
    """Short-circuit infeasible transport or relay stages as hard constraints."""
    transport_ok = transport_validation.get("status") in {"PASS", "FEASIBLE"}
    relay_status = relay_result.get("status") if isinstance(relay_result, dict) else getattr(relay_result, "status", None)
    relay_ok = relay_status == "PASS"
    comm_ok = True if communication_audit is None else bool(communication_audit.get("communication_feasible", False))
    checks = {"transport": transport_ok, "relay": relay_ok, "communication": comm_ok}
    return {"status": "PASS" if all(checks.values()) else "INFEASIBLE", "checks": checks,
            "reason": None if all(checks.values()) else "hard_constraint_failure"}
