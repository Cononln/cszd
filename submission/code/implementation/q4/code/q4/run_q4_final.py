"""Unified Q4 formal and clean-reproduction entry point."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .audit_q4_final import audit
from .generate_q4_figures import generate_figures
from .generate_q4_tables import generate_tables
from .problem_audit import run_q4a
from .q3_adapter import q4_root, results_root
from .q4_final import write_final
from .q4_small_cases import run_small_cases
from .run_q4_model import run_model
from .write_q4_freeze_report import write_report


def _clean(path: Path) -> None:
    path = path.resolve(); root = q4_root().resolve()
    if root not in path.parents or path == root or path.name not in {"results", "clean_results"}:
        raise ValueError(f"refusing to clean unsafe Q4 output path: {path}")
    if path.exists(): shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run_final(*, clean: bool = False, results_dir: Path | None = None) -> dict[str, Any]:
    old = os.environ.get("Q4_RESULTS_DIR")
    active = (results_dir or q4_root() / "results").resolve()
    os.environ["Q4_RESULTS_DIR"] = str(active)
    try:
        if clean: _clean(active)
        q4a = run_q4a()
        if q4a["status"] != "PASS": raise RuntimeError("Q4-A or Q3 interface gate failed")
        small = run_small_cases()
        if small["status"] != "PASS": raise RuntimeError("Q4 small-case validation failed")
        model = run_model()
        final = write_final(model, q4a["q3_interface_gate"])
        pre = audit(require_deliverables=False)
        if pre["status"] != "PASS": raise RuntimeError("Q4 pre-delivery audit failed")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="q4-delivery") as pool:
            figure_future = pool.submit(generate_figures)
            table_future = pool.submit(generate_tables)
            figures, tables = figure_future.result(), table_future.result()
        final_audit = audit(require_deliverables=True)
        report = {"status": "PASS" if final_audit["status"] == "PASS" else "FAIL", "results_dir": str(active),
                  "q4a_status": q4a["status"], "small_case_status": small["status"],
                  "selected_solution_ids": {key: value["solution_id"] for key, value in final["selected_solution"].items()},
                  "search_statistics": final["search_statistics"], "figures": figures, "tables": tables,
                  "final_audit": final_audit}
        (active / "q4_reproduction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_report()
        return report
    finally:
        if old is None: os.environ.pop("Q4_RESULTS_DIR", None)
        else: os.environ["Q4_RESULTS_DIR"] = old


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("formal", "reproduce"), default="formal")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--results-dir", type=Path)
    args = parser.parse_args()
    if args.mode == "reproduce" and args.results_dir is None:
        args.results_dir = q4_root() / "reproducibility" / "clean_results"; args.clean = True
    print(json.dumps(run_final(clean=args.clean, results_dir=args.results_dir), ensure_ascii=False, indent=2))
