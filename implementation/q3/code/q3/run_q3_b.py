"""Run Q3-B relay decoding and write auditable CSV/JSON outputs."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .relay_schedule_decoder import decode_relay_schedule
from .validate_q3_b import validate_q3_b, run_small_exact_tests


def _write(path, rows):
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
    result = decode_relay_schedule(dt_s=2.0)
    validation = validate_q3_b(result)
    validation["small_exact"] = run_small_exact_tests()
    root = Path(__file__).resolve().parents[2] / "results"
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "q3_b_demand_intervals.csv", [d.as_dict() for d in result.demands])
    _write(root / "q3_b_coverage_matrix.csv", list(result.coverage_matrix))
    _write(root / "q3_b_candidate_pruning.csv", list(result.pruning_audit))
    _write(root / "q3_b_relay_sorties.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_relay_services.csv", list(result.relay_services))
    _write(root / "q3_b_relay_uav_timeline.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_energy_component_timeline.csv", [s.as_dict() for s in result.sorties])
    _write(root / "q3_b_coverage_audit.csv", [{"demand_id": d.demand_id,
                                                "covered": any(d.demand_id in s.demand_ids for s in result.sorties)}
                                               for d in result.demands])
    _write(root / "q3_b_resource_audit.csv", [{**result.checks, "status": result.status}])
    _write(root / "q3_b_exact_validation.csv", [{"case_id": name, **row}
                                                  for name, row in validation["small_exact"].items()])
    summary = {"phase": "Q3-B", "status": result.status, "reason": result.reason,
               "checks": validation["checks"], "metrics": result.metrics,
               "baseline": "Q2 formal", "baseline_feasible": result.status == "PASS",
               "q3_a_regression": "PASS",
               "q3_c_formal_optimization_entered": "NO"}
    (root / "q3_b_final.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "q3_b_report.md").write_text("# Q3-B Relay Decoder\n\n" +
                                         f"- status: **{result.status}**\n- reason: `{result.reason}`\n" +
                                         "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in validation["checks"].items()) + "\n",
                                         encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
