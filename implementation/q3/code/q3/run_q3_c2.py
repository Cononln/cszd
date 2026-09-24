"""Reproducible Q3-C C2-A entry point; no C3 optimizer is invoked."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .c2_bottleneck import diagnose_relay_bottleneck
from .c2_seed_builder import run_c2a
from .relay_decoder_protocol import Q3BRelayDecoderAdapter
from .transport_adapter import (decode_transport_candidate, load_q2_formal_state,
                                relay_decoder_contract)


def _root() -> Path:
    path = Path(__file__).resolve().parents[2] / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value
                             for key, value in row.items()})


def _baseline_diagnostic(root: Path) -> dict[str, Any]:
    state = load_q2_formal_state()
    schedule, validation = decode_transport_candidate(state, cp_workers=1, time_limit_s=60.0, seed=0)
    relay_state, relay_schedule = relay_decoder_contract(state, schedule)
    result = Q3BRelayDecoderAdapter().decode_relay_schedule(
        relay_state, relay_schedule, candidate_spacing_m=1500.0)
    blind, overlap, pressure, summary = diagnose_relay_bottleneck(result)
    _csv(root / "q3_c2_baseline_blind_intervals.csv", blind)
    _csv(root / "q3_c2_baseline_overlap_matrix.csv", overlap)
    _csv(root / "q3_c2_baseline_relay_pressure.csv", pressure)
    payload = {"transport_validation": validation, "relay": {
        "decoder_status": result.decoder_status, "baseline_status": result.baseline_status,
        "solver_status": result.solver_status, "reason": result.reason,
        "metrics": result.metrics}, "bottleneck": summary}
    _json(root / "q3_c2_baseline_bottleneck.json", payload)
    return payload


def _candidate_log(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    log = []
    for row in rows:
        repaired = row["repaired"]
        transport = repaired["transport_validation"]
        relay = repaired["relay"]
        joint = repaired["joint"] or {}
        metrics = transport.get("metrics", {})
        relay_metrics = relay.get("metrics", {})
        log.append({
            "candidate_id": row["candidate_id"], "parent_id": row["parent_id"],
            "stage": row["repair_stage"], "operator": row["operator"],
            "transport_status": transport.get("status"),
            "relay_decoder_status": relay.get("decoder_status"),
            "relay_baseline_status": relay.get("baseline_status"),
            "joint_status": row["joint_status"],
            "WTD": metrics.get("WTD"), "transport_Cmax_s": metrics.get("Cmax_s"),
            "transport_energy_kwh": metrics.get("total_energy_kwh"), "transport_n_trips": metrics.get("n_trips"),
            "blind_count": relay_metrics.get("demand_count"),
            "relay_sorties": relay_metrics.get("relay_sortie_count"),
            "relay_energy_kwh": relay_metrics.get("relay_energy_kwh"),
            "joint_Cmax_s": max(float(metrics.get("Cmax_s", 0.0)), float(relay_metrics.get("relay_cmax_s", 0.0))),
            "total_energy_kwh": float(metrics.get("total_energy_kwh", 0.0)) + float(relay_metrics.get("relay_energy_kwh", 0.0)),
            "failure_reason": (joint.get("reason") or relay.get("reason") or
                               ";".join(repaired["violations"].get("transport", []))),
            "runtime_s": row["runtime_s"],
        })
    return log


def _write_seed_outputs(root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    repaired = candidate["repaired"]
    schedule = repaired["schedule"]
    relay = repaired["relay"]
    transport_metrics = repaired["transport_validation"]["metrics"]
    relay_metrics = relay["metrics"]
    seed = {
        "phase": "Q3-C-C2", "status": "PASS", "candidate_id": candidate["candidate_id"],
        "parent": candidate["parent_id"], "repair_stage": candidate["repair_stage"],
        "operators": [candidate["operator"], candidate["repair"]["operator"]],
        "joint_status": "PASS", "full_communication_pass": True, "outage_duration_s": 0.0,
        "transport_state": candidate["transport_state"], "schedule": schedule,
        "relay": relay, "transport_validation": repaired["transport_validation"],
        "relay_validation": repaired["relay_validation"], "joint_validation": repaired["joint"],
        "metrics": {"WTD": transport_metrics["WTD"], "transport_Cmax_s": transport_metrics["Cmax_s"],
                    "transport_energy_kwh": transport_metrics["total_energy_kwh"],
                    "transport_n_trips": transport_metrics["n_trips"],
                    "relay_sorties": relay_metrics["relay_sortie_count"],
                    "relay_energy_kwh": relay_metrics["relay_energy_kwh"],
                    "joint_Cmax_s": max(transport_metrics["Cmax_s"], relay_metrics["relay_cmax_s"]),
                    "total_energy_kwh": transport_metrics["total_energy_kwh"] + relay_metrics["relay_energy_kwh"]},
        "provenance": {"candidate_spacing_m": 1500.0, "source": "real Q2 validator + real Q3-B decoder"},
    }
    _json(root / "q3_c2_feasible_seed.json", seed)
    records = schedule["trip_records"]
    _csv(root / "q3_c2_transport_trips.csv", records)
    boxes = []
    for record in records:
        for sid, values in record["boxes_by_stop"].items():
            for box in values:
                boxes.append({"trip_id": record["trip_id"], "box": box, "sid": sid,
                              "gtype": record["gtype"], "uid": record["uid"],
                              "battery_id": record["battery_id"],
                              "delivery_time_s": record["delivery_by_box_s"][box]})
    _csv(root / "q3_c2_transport_boxes.csv", boxes)
    _csv(root / "q3_c2_transport_uav_timeline.csv", records)
    _csv(root / "q3_c2_transport_battery_timeline.csv", records)
    _csv(root / "q3_c2_relay_sorties.csv", relay["relay_sorties"])
    _csv(root / "q3_c2_relay_services.csv", relay["relay_services"])
    _csv(root / "q3_c2_relay_uav_timeline.csv", relay["relay_sorties"])
    _csv(root / "q3_c2_energy_component_timeline.csv", relay["relay_sorties"])
    _csv(root / "q3_c2_communication_audit.csv", relay["replay_audit"])
    _csv(root / "q3_c2_joint_resource_audit.csv", [repaired["joint"]])
    report = (
        "# Q3-C C2 First Joint-Feasible Seed\n\n"
        f"- candidate: `{candidate['candidate_id']}`\n"
        f"- parent: `{candidate['parent_id']}`\n"
        "- joint validator: **PASS**\n"
        "- full communication outage duration: **0 s**\n"
        f"- transport Cmax: {seed['metrics']['transport_Cmax_s']:.3f} s\n"
        f"- relay sorties: {seed['metrics']['relay_sorties']}\n"
        f"- total energy: {seed['metrics']['total_energy_kwh']:.6f} kWh\n")
    (root / "q3_c2_feasible_seed_report.md").write_text(report, encoding="utf-8")
    return seed


def run() -> dict[str, Any]:
    root = _root()
    baseline = _baseline_diagnostic(root)
    c2a = run_c2a()
    candidates = c2a["candidates"]
    audit = [{"candidate_id": row["candidate_id"], "repair": row["repair"],
              "baseline_violations": row["baseline"]["violations"],
              "repaired_violations": row["repaired"]["violations"]} for row in candidates]
    validation = [{"candidate_id": row["candidate_id"], "joint_status": row["joint_status"],
                   "transport_validation": row["repaired"]["transport_validation"],
                   "relay_validation": row["repaired"]["relay_validation"],
                   "joint_validation": row["repaired"]["joint"]} for row in candidates]
    _json(root / "q3_c2a_candidates.json", c2a)
    _json(root / "q3_c2a_repair_audit.json", audit)
    _json(root / "q3_c2a_validation.json", validation)
    log = _candidate_log(candidates)
    _csv(root / "q3_c2_candidate_log.csv", log)
    feasible = [row for row in candidates if row["feasible_seed_found"]]
    seed = _write_seed_outputs(root, feasible[0]) if feasible else None
    (root / "q3_c2a_summary.md").write_text(
        "# Q3-C C2-A Temporal Repair\n\n"
        f"- candidates evaluated: {len(candidates)}\n"
        f"- transport-validator PASS: {c2a['transport_feasible_count']}\n"
        f"- real relay-decoder evaluations: {c2a['relay_evaluated_count']}\n"
        f"- joint-validator PASS: {c2a['joint_feasible_count']}\n"
        f"- baseline bottleneck: `{baseline['bottleneck']['primary_bottleneck']}`\n"
        f"- C2-A status: **{c2a['status']}**\n",
        encoding="utf-8")
    return {"baseline": baseline, "c2a": c2a, "seed": seed}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
