"""Compare formal Q4 results with a clean reproduction.

The exhaustive search is deterministic.  Wall-clock runtime is intentionally
excluded from the semantic comparison because it is an execution measurement,
not a model result.  Paths, hashes and report locations are also kept outside
the model comparison so the evidence remains portable between output roots.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .q3_adapter import q4_root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_final(value: dict[str, Any]) -> dict[str, Any]:
    """Drop only execution metadata that is expected to vary between runs."""
    result = json.loads(json.dumps(value, ensure_ascii=False))
    result.get("metadata", {}).pop("git_revision", None)
    result.get("search_statistics", {}).pop("runtime_s", None)
    return result


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _portable(value: Any, formal_root: Path, clean_root: Path) -> Any:
    """Normalize output-root paths embedded by external PDF QA utilities."""
    if isinstance(value, dict):
        return {key: _portable(item, formal_root, clean_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item, formal_root, clean_root) for item in value]
    if isinstance(value, str):
        return value.replace(str(formal_root), "<q4-results>").replace(str(clean_root), "<q4-results>")
    return value


def compare(*, write: bool = True) -> dict[str, Any]:
    root = q4_root()
    formal = root / "results"
    clean = root / "reproducibility" / "clean_results"
    required = [
        "q4_final.json",
        "q4_final_audit.json",
        "q4_q3_interface_validation.json",
        "q4_small_case_validation.json",
        "q4_failure_taxonomy.json",
        "q4_baseline.json",
        "q4_baseline_validation.json",
        "q4_2group_candidates.json",
        "q4_3group_candidates.json",
        "q4_feasible_pool.json",
        "q4_candidate_log.csv",
    ]
    missing = [name for name in required if not (formal / name).exists() or not (clean / name).exists()]
    # q4_final has a recorded wall-clock runtime, so it is checked by the
    # semantic rule below rather than byte-for-byte.
    stable_files = [name for name in required if name != "q4_final.json"]
    exact_files = {}
    if not missing:
        for name in stable_files:
            exact_files[name] = {
                "formal_sha256": _sha(formal / name),
                "clean_sha256": _sha(clean / name),
                "equal": _sha(formal / name) == _sha(clean / name),
            }
    semantic_equal = False
    selected_equal = False
    final_status = "MISSING"
    if not missing:
        formal_final = _json(formal / "q4_final.json")
        clean_final = _json(clean / "q4_final.json")
        semantic_equal = _semantic_final(formal_final) == _semantic_final(clean_final)
        selected_equal = formal_final.get("selected_solution") == clean_final.get("selected_solution")
        final_status = "PASS" if semantic_equal and selected_equal else "FAIL"

    figure_checks = {}
    formal_figures = formal / "figures"
    clean_figures = clean / "figures"
    for name in ("q4_figure_manifest.json", "Q4_Figure_Contract.md"):
        fp, cp = formal_figures / name, clean_figures / name
        if fp.exists() and cp.exists() and name.endswith(".json"):
            f, c = _json(fp), _json(cp)
            # The source hash changes with the runtime field; the QA and
            # artifact manifest itself must otherwise have the same meaning.
            f.pop("source_sha256", None)
            c.pop("source_sha256", None)
            f = _portable(f, formal, clean)
            c = _portable(c, formal, clean)
            figure_checks[name] = {
                "semantic_equal": f == c,
                "formal_status": f.get("status"),
                "clean_status": c.get("status"),
            }
        elif fp.exists() and cp.exists():
            figure_checks[name] = {"exact_equal": _sha(fp) == _sha(cp)}
        else:
            figure_checks[name] = {"missing": True}

    audit_pass = all(_json(path).get("status") == "PASS" for path in (
        formal / "q4_final_audit.json", clean / "q4_final_audit.json",
        formal / "q4_q3_interface_validation.json", clean / "q4_q3_interface_validation.json",
        formal / "q4_small_case_validation.json", clean / "q4_small_case_validation.json")) if not missing else False
    exact_pass = all(row["equal"] for row in exact_files.values()) if exact_files else False
    status = "PASS" if not missing and final_status == "PASS" and exact_pass and audit_pass and all(
        row.get("semantic_equal", row.get("exact_equal", False)) for row in figure_checks.values()) else "FAIL"
    report: dict[str, Any] = {
        "phase": "Q4 clean reproduction comparison",
        "status": status,
        "formal_results_dir": "implementation/q4/results",
        "clean_results_dir": "implementation/q4/reproducibility/clean_results",
        "comparison_rule": "semantic q4_final equality; execution runtime excluded; stable evidence files exact",
        "missing_files": missing,
        "q4_final": {"status": final_status, "semantic_equal": semantic_equal, "selected_solution_equal": selected_equal},
        "stable_evidence_exact": exact_pass,
        "evidence_files": exact_files,
        "audit_statuses_pass": audit_pass,
        "figure_checks": figure_checks,
    }
    if write:
        for destination in (formal, clean):
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "q4_reproduction_comparison.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(compare(), ensure_ascii=False, indent=2))
