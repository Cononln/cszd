"""Run the bounded C2-B combination neighborhood after C2-A."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .c2_seed_builder import run_c2b
from .run_q3_c2 import _candidate_log, _csv, _json, _write_seed_outputs


def run() -> dict:
    configured = os.environ.get("Q3_RESULTS_DIR")
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parents[2] / "results"
    root.mkdir(parents=True, exist_ok=True)
    result = run_c2b()
    _json(root / "q3_c2b_candidates.json", result)
    _json(root / "q3_c2b_results.json", result)
    _csv(root / "q3_c2b_candidate_log.csv", _candidate_log(result["candidates"]))
    validations = [{"candidate_id": row["candidate_id"], "joint_status": row["joint_status"],
                    "transport_validation": row["repaired"]["transport_validation"],
                    "relay_validation": row["repaired"]["relay_validation"],
                    "joint_validation": row["repaired"]["joint"]} for row in result["candidates"]]
    _json(root / "q3_c2b_validation.json", validations)
    feasible = [row for row in result["candidates"] if row["feasible_seed_found"]]
    if feasible and not (root / "q3_c2_feasible_seed.json").exists():
        _write_seed_outputs(root, feasible[0])
    (root / "q3_c2b_summary.md").write_text(
        "# Q3-C C2-B Bounded Combination Search\n\n"
        f"- candidates generated: {result['candidate_count']}\n"
        f"- transport validator PASS: {result['transport_feasible_count']}\n"
        f"- real relay evaluations: {result['relay_evaluated_count']}\n"
        f"- final joint validator PASS: {result['joint_feasible_count']}\n"
        f"- C2-B status: **{result['status']}**\n",
        encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
