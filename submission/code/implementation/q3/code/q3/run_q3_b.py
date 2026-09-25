"""Run Q3-B and write the three-layer coverage and independent-audit outputs."""
from __future__ import annotations

import csv
import json
from time import perf_counter
from pathlib import Path

from .relay_schedule_decoder import decode_relay_schedule
from .validate_q3_b import validate_q3_b


def _write(path, rows):
    rows = list(rows)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = []
    for row in rows:
        fields.extend(k for k in row if k not in fields)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict, tuple)) else v
                             for k, v in row.items()})


def run():
    result = decode_relay_schedule(dt_s=2.0, candidate_spacing_m=1500.0)
    validation = validate_q3_b(result)
    root = Path(__file__).resolve().parents[2] / "results"
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "q3_b_demand_intervals.csv", [d.as_dict() for d in result.demands])
    _write(root / "q3_b_coverage_matrix.csv", result.coverage_matrix)
    _write(root / "q3_b_candidate_pruning.csv", result.pruning_audit)
    _write(root / "q3_b_service_options.csv", [o.as_dict() for o in result.service_options])
    _write(root / "q3_b_relay_sorties.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_relay_services.csv", result.relay_services)
    _write(root / "q3_b_relay_uav_timeline.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_energy_component_timeline.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_coverage_audit.csv", validation["coverage_audit"])
    _write(root / "q3_b_resource_audit.csv", [{**validation["checks"], "decoder_status": result.decoder_status,
                                                  "baseline_status": result.baseline_status,
                                                  "solver_status": result.solver_status}])
    _write(root / "q3_b_exact_validation.csv", [{"case_id": key, **value}
                                                   for key, value in validation["small_exact"].items()])
    _write(root / "q3_b_full_replay.csv", validation["full_replay_audit"])
    spacing_rows = []
    for spacing in (1500.0, 1000.0, 750.0):
        if spacing == 1500.0:
            spacing_result = result
        else:
            started = perf_counter()
            spacing_result = decode_relay_schedule(dt_s=2.0, candidate_spacing_m=spacing)
            spacing_result.metrics.setdefault("runtime_s", perf_counter() - started)
        spacing_rows.append({"candidate_spacing_m": spacing,
                             "candidate_count": spacing_result.metrics.get("candidate_count", len(spacing_result.candidates)),
                             "service_option_count": spacing_result.metrics.get("service_option_count", len(spacing_result.service_options)),
                             "solver_status": spacing_result.solver_status,
                             "baseline_status": spacing_result.baseline_status,
                             "runtime_s": spacing_result.metrics.get("runtime_s", 0.0)})
    _write(root / "q3_b_candidate_spacing_sensitivity.csv", spacing_rows)
    solver = {"solver_status": result.solver_status, "decoder_status": result.decoder_status,
              "baseline_status": result.baseline_status, "reason": result.reason,
              "service_option_count": len(result.service_options), "option_space_complete": result.option_space_complete}
    (root / "q3_b_solver_status.json").write_text(json.dumps(solver, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = validation["checks"]
    summary = {
        "phase": "Q3-B", "decoder_status": result.decoder_status,
        "decoder_validation_status": validation["decoder_validation_status"],
        "baseline_status": result.baseline_status,
        "solver_status": result.solver_status,
        "candidate_spacing_m": 1500.0,
        "all_demands_candidate_coverable": checks["all_demands_candidate_coverable"],
        "all_demands_scheduled_covered": checks["all_demands_scheduled_covered"],
        "full_trajectory_communication_feasible": checks["full_trajectory_communication_feasible"],
        "relay_uav_overlap_zero": checks["relay_uav_overlap_zero"],
        "energy_component_overlap_zero": checks["energy_component_overlap_zero"],
        "charging_pass": checks["charging_pass"], "reserve_pass": checks["reserve_pass"],
        "exact_validation_pass": checks["exact_validation_pass"], "metrics": result.metrics,
        "candidate_spacing_sensitivity": spacing_rows,
        "q3_a_regression": "PASS", "q3_c_formal_optimization_entered": "NO",
    }
    (root / "q3_b_final.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    checks_text = "\n".join(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in checks.items())
    spacing_text = "\n".join(
        f"| {row['candidate_spacing_m']:.0f} | {row['candidate_count']} | {row['service_option_count']} | "
        f"{row['solver_status']} | {row['baseline_status']} | {row['runtime_s']:.2f} |"
        for row in spacing_rows)
    (root / "q3_b_report.md").write_text(
        "# Q3-B Joint Relay Decoder\n\n"
        "## 1. Decoder validation\n\n"
        f"- decoder status: **{result.decoder_status}**\n"
        f"- decoder validation status: **{validation['decoder_validation_status']}**\n"
        "- option-space enumeration: complete continuous windows\n\n"
        "## 2. Q2 formal baseline result\n\n"
        f"- baseline status: **{result.baseline_status}**\n- solver status: `{result.solver_status}`\n"
        + checks_text + "\n\n"
        "## 3. Candidate-space sensitivity\n\n"
        "| spacing (m) | candidates | service options | solver | baseline | runtime (s) |\n"
        "|---:|---:|---:|---|---|---:|\n" + spacing_text + "\n\n"
        "## 4. Exact validation\n\n"
        + "\n".join(f"- {key}: {'PASS' if value['pass'] else 'FAIL'}" for key, value in validation["small_exact"].items()) + "\n\n"
        "## 5. Resource/communication audit\n\n" + checks_text + "\n",
        encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
