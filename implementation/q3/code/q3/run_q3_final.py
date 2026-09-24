"""One-command formal Q3 reproduction path, including clean-output verification."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .audit_q3_final import audit
from .generate_q3_figures import generate_figures
from .q3_final import write_final
from .run_q3_c2 import run as run_c2a
from .run_q3_c2b import run as run_c2b
from .write_q3_tables import write_tables


def _safe_clean(path: Path) -> None:
    resolved = path.resolve()
    q3_root = Path(__file__).resolve().parents[2]
    if q3_root not in resolved.parents or resolved == q3_root or resolved.name not in {"results", "clean_results"}:
        raise ValueError(f"refusing to clean unsafe Q3 output path: {resolved}")
    # A dedicated reproduction directory is wholly owned by this entry point.
    if resolved.name == "clean_results":
        if resolved.exists():
            shutil.rmtree(resolved)
        resolved.mkdir(parents=True, exist_ok=True)
        return
    # ``results`` also contains frozen Q3-A/B evidence.  C2/final runs must not
    # erase those upstream audit artifacts merely because they are not rebuilt
    # by this Q3-C formal entry point.
    resolved.mkdir(parents=True, exist_ok=True)
    prefixes = ("q3_c2", "q3_final", "q3_feasible_pool", "q3_failure_taxonomy", "q3_reproduction_report")
    for child in resolved.iterdir():
        if child.name in {"figures", "tables", "Q3_FREEZE_REPORT.md"} or child.name.startswith(prefixes):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def run_final(*, clean: bool = False, results_dir: Path | None = None) -> dict[str, Any]:
    old_results = os.environ.get("Q3_RESULTS_DIR")
    if results_dir is not None:
        os.environ["Q3_RESULTS_DIR"] = str(results_dir.resolve())
    try:
        active = Path(os.environ.get("Q3_RESULTS_DIR", Path(__file__).resolve().parents[2] / "results"))
        if clean:
            _safe_clean(active)
        else:
            active.mkdir(parents=True, exist_ok=True)
        c2a = run_c2a()
        c2b = run_c2b()
        final = write_final()
        pre_delivery_audit = audit(require_deliverables=False)
        if pre_delivery_audit["status"] != "PASS":
            raise RuntimeError("pre-delivery final audit failed; figures/tables were not generated")
        # Figures and tables are independent read-only derivatives of one frozen JSON source.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="q3-final-delivery") as pool:
            figure_future = pool.submit(generate_figures)
            table_future = pool.submit(write_tables)
            figures = figure_future.result()
            tables = table_future.result()
        final_audit = audit(require_deliverables=True)
        result = {"status": "PASS" if final_audit["status"] == "PASS" else "FAIL", "results_dir": str(active.resolve()),
                  "c2a": {key: c2a["c2a"][key] for key in ("status", "candidate_count", "joint_feasible_count")},
                  "c2b": {key: c2b[key] for key in ("status", "candidate_count", "joint_feasible_count")},
                  "selected_solution_id": final["selected_solution"]["solution_id"],
                  "figures": figures, "tables": tables, "final_audit": final_audit}
        (active / "q3_reproduction_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        if old_results is None:
            os.environ.pop("Q3_RESULTS_DIR", None)
        else:
            os.environ["Q3_RESULTS_DIR"] = old_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the complete formal Q3 pipeline.")
    parser.add_argument("--mode", choices=("formal", "reproduce"), default="formal")
    parser.add_argument("--clean", action="store_true", help="clean the selected Q3 output directory before running")
    parser.add_argument("--results-dir", type=Path, help="Q3-only output directory (results or clean_results)")
    args = parser.parse_args()
    if args.mode == "reproduce" and args.results_dir is None:
        args.results_dir = Path(__file__).resolve().parents[2] / "reproducibility" / "clean_results"
        args.clean = True
    print(json.dumps(run_final(clean=args.clean, results_dir=args.results_dir), ensure_ascii=False, indent=2))
