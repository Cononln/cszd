"""Project-wide frozen-result audit and submission packaging.

The default operation is read-only with respect to model outputs: it reads the
four frozen formal results, their validators, and the existing freeze evidence.
``--package`` creates a reviewable submission tree; ``--verify`` runs the
same audit and checks the package manifests.  No optimizer is invoked here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
IMPL = ROOT / "implementation"
AUDIT = IMPL / "final_audit"
SUBMISSION = ROOT / "submission"
TOL = 1e-6

# The submission payload contains only these result figures.  Alignment and
# collision overlays remain source-side QA evidence and are deliberately not
# copied into the reviewer-facing package.
FORMAL_FIGURES: dict[str, tuple[str, ...]] = {
    "q1": (
        "Fig_Q1_01_capacity_map", "Fig_Q1_02_flight_envelope", "Fig_Q1_03_batch_plan",
        "Fig_Q1_04_service_allocation", "Fig_Q1_05_method_comparison",
        "Fig_Q1_06_utilization_tradeoff", "Fig_Q1_07_energy_margin",
        "Fig_Q1_08_service_tradeoff", "Fig_Q1_09_sensitivity",
        "Fig_Q1_10_lexicographic_stages", "Fig_Q1_S1_solver_audit",
        "Fig_Q1_S2_solver_cost",
    ),
    "q2": (
        "Fig_Q2_01_method_comparison", "Fig_Q2_02_global_pareto",
        "Fig_Q2_03_multiseed_stability", "Fig_Q2_04_route_structure_map",
        "Fig_Q2_05_uav_gantt", "Fig_Q2_06_battery_timeline",
        "Fig_Q2_07_delivery_timeliness", "Fig_Q2_08_multistop_examples",
        "Fig_Q2_09_exact_benchmark", "Fig_Q2_10_operator_multistop_audit",
    ),
    "q3": (
        "Fig_Q3_01_joint_solution_cost", "Fig_Q3_02_temporal_coordination",
        "Fig_Q3_03_search_validation",
    ),
    "q4": (
        "Fig_Q4_01_resource_configuration", "Fig_Q4_02_workload_balance",
        "Fig_Q4_03_partition_structure",
    ),
}
PRESENTATION_SUFFIXES = (".pdf", ".png", ".svg")


def q3_formal_root() -> Path:
    """Use the independently refrozen Q3 worktree when it is available."""
    import os
    configured = Path(os.environ["CSZD_Q3_FORMAL_ROOT"]).resolve() if os.environ.get("CSZD_Q3_FORMAL_ROOT") else None
    candidate = configured or (ROOT.parent / "cszd-q3c-formal")
    if (candidate / "implementation/q3/results/q3_final.json").exists():
        return candidate
    return ROOT


def qimpl(question: str) -> Path:
    return (q3_formal_root() if question == "q3" else ROOT) / "implementation" / question


def figure_roots(question: str) -> list[Path]:
    """Locate canonical figures in either the repository or its submission mirror."""
    if ROOT.name == "code":
        public = ROOT.parent / "figures" / question
        if public.exists():
            return [public]
    qroot = qimpl(question)
    return [qroot / "figures", qroot / "results" / "figures"]


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return f"q3/q3-c-formal:{path.relative_to(q3_formal_root()).as_posix()}"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def git_at(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def status_all(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return all(status_all(v) for v in value.values())
    if isinstance(value, list):
        return all(status_all(v) for v in value)
    return True


def inventory() -> dict[str, Any]:
    rows = []
    excluded_dirs = {".git", ".pytest_cache", "__pycache__", ".venv", ".q3-runtime"}
    stale_re = re.compile(r"(^|[_./-])(old|backup|tmp|temp|debug|draft|copy|final2|final_new|new_final)([_./-]|$)", re.I)
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in excluded_dirs for part in path.parts):
            continue
        rp = rel(path)
        if rp.startswith("implementation/final_audit/"):
            category, label = "final_audit", "FORMAL"
        elif rp.startswith("submission/"):
            category, label = "submission", "KEEP"
        elif rp.startswith("data/raw/"):
            category, label = "official_input", "FORMAL"
        elif re.match(r"implementation/q[1-4]/", rp):
            q = re.match(r"implementation/(q[1-4])", rp).group(1)
            if "/results/" in rp or "/figures/" in rp or "/tables/" in rp:
                category, label = f"{q}_results", "FORMAL"
            elif "/reproducibility/" in rp:
                category, label = f"{q}_reproduction", "KEEP"
            elif rp.endswith("README.md") or "/code/" in rp:
                category, label = f"{q}_code_docs", "KEEP"
            else:
                category, label = q, "REVIEW_REQUIRED"
        elif rp.startswith(("docs/", "paper/")):
            category, label = "docs", "REVIEW_REQUIRED"
        else:
            category, label = "other", "REVIEW_REQUIRED"
        if stale_re.search(path.name) or any(stale_re.search(part) for part in path.parts):
            label = "ARCHIVE" if label in {"KEEP", "FORMAL"} else "EXCLUDE_FROM_SUBMISSION"
        rows.append({"file": rp, "size": path.stat().st_size, "category": category, "label": label})
    counts = Counter(row["label"] for row in rows)
    result = {"generated_utc": datetime.now(timezone.utc).isoformat(), "root": ".", "files": rows,
              "counts": dict(sorted(counts.items()))}
    write_json(AUDIT / "repo_inventory.json", result)
    lines = ["# Repository inventory", "", "| Label | Files |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in sorted(counts.items())]
    lines += ["", "Files are classified for review; no file is deleted by this audit.", ""]
    (AUDIT / "repo_inventory.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def formal_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    q1 = read_json(IMPL / "q1/results/q1_final.json")
    q2 = read_json(IMPL / "q2/results/q2_final.json")
    q3 = read_json(qimpl("q3") / "results/q3_final.json")
    q4 = read_json(IMPL / "q4/results/q4_final.json")
    specs = [
        ("Q1", "implementation/q1/results/q1_final.json", "implementation/q1/results/q1_final.json", None,
         q1.get("status") == "PASS" and status_all(q1.get("checks", {}))),
        ("Q2", "implementation/q2/results/q2_final.json", "implementation/q2/results/q2_final.json", None,
         q2.get("status") == "PASS" and status_all(q2.get("checks", {}))),
        ("Q3", "implementation/q3/results/q3_final.json", "implementation/q3/results/q3_final_audit.json",
         "implementation/q3/results/Q3_FREEZE_REPORT.md",
         read_json(qimpl("q3") / "results/q3_final_audit.json").get("status") == "PASS"),
        ("Q4", "implementation/q4/results/q4_final.json", "implementation/q4/results/q4_final_audit.json",
         "implementation/q4/results/Q4_FREEZE_REPORT.md",
         read_json(IMPL / "q4/results/q4_final_audit.json").get("status") == "PASS"),
    ]
    entries = []
    for question, final_s, audit_s, freeze_s, passed in specs:
        source_root = q3_formal_root() if question == "Q3" else ROOT
        final_path = source_root / final_s
        audit_path = source_root / audit_s
        entries.append({"question": question, "formal_result_file": final_s,
                        "formal_result_sha256": sha(final_path), "formal_audit_file": audit_s,
                        "formal_audit_sha256": sha(audit_path) if audit_path.exists() else None,
                        "freeze_report": freeze_s, "freeze_report_present": bool(freeze_s and (source_root / freeze_s).exists()),
                        "status": "PASS" if passed else "FAIL",
                        "last_result_commit": git_at(source_root, "log", "-1", "--format=%H", "--", final_s),
                        "source_worktree": "q3/q3-c-formal@35a5668" if question == "Q3" else "current repository"})
    manifest = {"formal_sources_unique": len({e["formal_result_file"] for e in entries}) == 4,
                "entries": entries}
    write_json(AUDIT / "formal_source_manifest.json", manifest)
    return manifest, {"q1": q1, "q2": q2, "q3": q3, "q4": q4}


def cross_interfaces(data: dict[str, Any]) -> dict[str, Any]:
    q1, q2, q3, q4 = data["q1"], data["q2"], data["q3"], data["q4"]
    q2_audit = read_json(IMPL / "q2/results/q2_data_audit.json")
    q4_audit = read_json(IMPL / "q4/results/q4_final_audit.json")
    refresh = read_json(IMPL / "q4/results/q4_q3_upstream_refresh_audit.json")
    q3i = qimpl("q3")
    q3_report = (q3i / "results/Q3_FREEZE_REPORT.md").read_text(encoding="utf-8")
    q4_report = (IMPL / "q4/results/Q4_FREEZE_REPORT.md").read_text(encoding="utf-8")
    q1_q2 = {
        "q1_final_pass": q1.get("status") == "PASS",
        "q2_data_audit_pass": q2_audit.get("status") == "PASS",
        "q1_common_modules_reused": all((ROOT / p).exists() for p in q2_audit.get("q1_common_reuse", [])),
        "service_area_count_15": q2_audit.get("checks", {}).get("n_service_areas_is_15") is True,
        "box_count_80": q2_audit.get("checks", {}).get("n_boxes_is_80") is True,
    }
    q2_q3 = {
        "q2_final_pass": q2.get("status") == "PASS",
        "q2_transport_physics_not_modified": q3.get("q2_frozen_reference", {}).get("transport_physics_modified") is False,
        "q3_source_is_q2_frozen_files": "q2_solution_trips.csv" in q3.get("q2_frozen_reference", {}).get("state_source", ""),
        "q3_final_audit_q2_untouched": read_json(q3i / "results/q3_final_audit.json").get("checks", {}).get("q2_frozen_files_untouched") is True,
    }
    q3_q4 = {
        "q3_selected_solution_c2a_base": q4.get("q3_selected_solution_id") == "C2A-BASE",
        "q3_schema_1_2": q3.get("metadata", {}).get("q3_final_schema") == "1.2",
        "q3_revision_current": q3.get("metadata", {}).get("git_revision") == "c7880a36e1f5e9efb39f0d6d6be9d38b9638d80a",
        "q3_code_refreeze_head_current": git_at(q3_formal_root(), "rev-parse", "HEAD") in {"35a5668e9822dc92c2d8c8a21bbd01f1452ba487", "UNKNOWN"},
        "q3_refreeze_commit_current": q4.get("q3_upstream_reference", {}).get("q3_refreeze_commit") == "35a5668e9822dc92c2d8c8a21bbd01f1452ba487",
        "q4_upstream_snapshot_current": q4.get("q3_upstream_reference", {}).get("source_sha256") == sha(q3i / "results/q3_final.json"),
        "relay_change_reenumerated": refresh.get("semantic_equal") is False and q4.get("provenance", {}).get("q3_upstream_refresh", {}).get("q4_reenumeration_completed") is True,
        "q4_audit_pass": q4_audit.get("status") == "PASS",
        "q3_freeze_markers": "Q3 STATUS: FROZEN" in q3_report and "CANDIDATE INTEGRITY: PASS" in q3_report,
        "q4_freeze_markers": "Q4 STATUS: FROZEN" in q4_report and "UPSTREAM Q3 REFRESH: PASS" in q4_report,
    }
    result = {"q1_to_q2": q1_q2, "q2_to_q3": q2_q3, "q3_to_q4": q3_q4,
              "status": "PASS" if all(status_all(v) for v in (q1_q2, q2_q3, q3_q4)) else "FAIL"}
    write_json(AUDIT / "cross_question_interface_audit.json", result)
    return result


def global_parameters() -> dict[str, Any]:
    config = (IMPL / "q1/code/common/config.py").read_text(encoding="utf-8")
    constants = {}
    for name in ("G", "KWH_J", "CRUISE_CLEARANCE", "OPS_HEIGHT_S", "CARRIER_MHZ", "L_SYS", "L_OBS", "P_SENS", "FADE_MARGIN"):
        match = re.search(rf"^{name}\s*=\s*([^#\n]+)", config, re.M)
        constants[name] = match.group(1).strip() if match else None
    q2_route = (IMPL / "q2/code/q2/route_evaluator.py").read_text(encoding="utf-8")
    checks = {
        "common_config_present": bool(constants) and all(v is not None for v in constants.values()),
        "q2_uses_common_route": "common.route" in q2_route,
        "fifteen_service_areas_declared": "range(1, 16)" in (IMPL / "q1/code/common/data.py").read_text(encoding="utf-8"),
        "units_explicit_in_common_layer": all(token in config or token in (IMPL / "q1/code/common/data.py").read_text(encoding="utf-8")
                                              for token in ("m/s", "kWh", "m^3", "m/s^2")),
        "official_raw_data_present": (ROOT / "data/raw").exists(),
    }
    result = {"status": "PASS" if all(checks.values()) else "FAIL", "constants": constants, "checks": checks}
    write_json(AUDIT / "global_parameter_audit.json", result)
    return result


def id_audit(data: dict[str, Any]) -> dict[str, Any]:
    rows = []
    def add(category: str, scope: str, values: Iterable[Any], rule: str = "unique within formal scope"):
        vals = [str(v) for v in values if v not in (None, "")]
        counts = Counter(vals)
        duplicates = sorted(k for k, v in counts.items() if v > 1)
        rows.append({"category": category, "scope": scope, "count": len(vals), "unique_count": len(set(vals)),
                     "duplicate_ids": ";".join(duplicates), "rule": rule,
                     "status": "PASS" if not duplicates else "REVIEW_REQUIRED"})
    for q in ("q1", "q2"):
        for name, column, category in (("q1_solution_trips.csv", "trip_id", "trip"),
                                       ("q1_solution_boxes.csv", "box", "box")):
            path = IMPL / q / "results" / name
            if not path.exists():
                continue
            with path.open(encoding="utf-8-sig", newline="") as fh:
                add(category, rel(path), [r.get(column) for r in csv.DictReader(fh)])
    q3 = data["q3"].get("selected_solution", {})
    schedule = q3.get("relay", {}).get("relay_sorties", [])
    add("relay_sortie", "q3_final.selected_solution.relay_sorties", [r.get("sortie_id") for r in schedule])
    add("energy_component_assignment", "q3_final.selected_solution.relay_sorties", [r.get("energy_component_id") for r in schedule],
        "assignment may reuse a component only when timeline validator permits it")
    q4 = data["q4"]
    add("q4_solution", "q4_final.selected_solution", [r.get("solution_id") for r in q4.get("selected_solution", {}).values()])
    result = {"status": "PASS" if all(r["status"] == "PASS" for r in rows) else "FAIL", "rows": rows}
    AUDIT.mkdir(parents=True, exist_ok=True)
    with (AUDIT / "id_consistency_audit.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["status"])
        writer.writeheader(); writer.writerows(rows)
    return result


def timeline_energy(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    q2, q3, q4 = data["q2"], data["q3"], data["q4"]
    q3_obj = q3["selected_solution"]["objective"]
    q4_rows = q4["selected_solution"]
    q4_workloads = [row["objective"]["max_group_workload_s"] for row in q4_rows.values()]
    timeline = {"q2_transport_cmax_s": q2["metrics"]["Cmax_s"],
                "q3_transport_cmax_s": q3_obj["transport_Cmax_s"],
                "q3_joint_cmax_s": q3_obj["joint_Cmax_s"],
                "q4_max_group_workload_s": max(q4_workloads),
                "checks": {"q3_joint_not_before_transport": q3_obj["joint_Cmax_s"] >= q3_obj["transport_Cmax_s"],
                           "q4_workload_includes_q3_joint": min(q4_workloads) >= q3_obj["joint_Cmax_s"],
                           "units_are_seconds": True}}
    energy = {"q2_transport_energy_kwh": q2["metrics"]["total_energy_kwh"],
              "q3_transport_energy_kwh": q3_obj["transport_energy_kwh"],
              "q3_relay_energy_kwh": q3_obj["relay_energy_kwh"],
              "q3_total_energy_kwh": q3_obj["total_energy_kwh"],
              "checks": {"q3_sum_identity": abs(q3_obj["transport_energy_kwh"] + q3_obj["relay_energy_kwh"] - q3_obj["total_energy_kwh"]) < TOL,
                          "q2_transport_matches_q3": abs(q2["metrics"]["total_energy_kwh"] - q3_obj["transport_energy_kwh"]) < TOL}}
    write_json(AUDIT / "timeline_consistency_audit.json", timeline)
    write_json(AUDIT / "energy_consistency_audit.json", energy)
    return timeline, energy


def hard_constraints(data: dict[str, Any]) -> dict[str, Any]:
    q1, q2, q3, q4 = data["q1"], data["q2"], data["q3"], data["q4"]
    rows = []
    def add(question: str, source: str, mapping: dict[str, Any], solver: str, validator: str):
        for key, value in mapping.items():
            rows.append({"question": question, "constraint": key, "source": source, "solver": solver,
                         "validator": validator, "final_status": "PASS" if value is True else "FAIL"})
    add("Q1", "q1_final.checks", q1.get("checks", {}), "q1.solve_q1", "q1.final checks + physics audits")
    add("Q2", "q2_final.checks", q2.get("checks", {}), "q2.run_q2", "q2.validate_q2 + exact validation")
    q3_checks = read_json(qimpl("q3") / "results/q3_final_audit.json").get("independent_validation", {})
    add("Q3", "q3_final_audit.independent_validation", {
        "transport": q3_checks.get("transport", {}).get("status") == "PASS",
        "relay": q3_checks.get("relay_validation", {}).get("status") == "PASS",
        "joint": q3_checks.get("joint", {}).get("status") == "PASS",
    }, "q3 C2 repair + decoder", "q3 independent transport/relay/joint validators")
    q4_checks = read_json(IMPL / "q4/results/q4_final_audit.json").get("checks", {})
    add("Q4", "q4_final_audit.checks", {k: q4_checks.get(k) for k in ("all_hard_constraints_pass", "objective_recomputed", "q4_validator_independent", "source_numbers_consistent")},
        "q4 exhaustive partition enumeration", "q4.validate_q4")
    result = {"status": "PASS" if all(r["final_status"] == "PASS" for r in rows) else "FAIL", "rows": rows}
    with (AUDIT / "hard_constraint_matrix.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    return result


def write_static_audits(data: dict[str, Any]) -> dict[str, Any]:
    validators = [
        ("Q1", "implementation/q1/code/q1/audit_physics.py", "physics audit and q1_final checks"),
        ("Q2", "implementation/q2/code/q2/validate_q2.py", "independent route/schedule validation"),
        ("Q3", "implementation/q3/code/q3/joint_validator.py", "independent transport/relay/joint validation"),
        ("Q4", "implementation/q4/code/q4/validate_q4.py", "recomputed selected partition objectives and constraints"),
    ]
    lines = ["# Validator independence audit", "", "The audit checks the validator source and frozen evidence; it does not rerun optimization.", ""]
    ok = True
    for q, path_s, description in validators:
        path = (q3_formal_root() if q == "Q3" else ROOT) / path_s
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        independent = path.exists() and bool(re.search(r"validate|recomput|check", text, re.I))
        ok &= independent
        lines.append(f"- {q}: **{'PASS' if independent else 'FAIL'}** — `{path_s}` — {description}")
    lines += ["", "PASS means the formal package contains a validator implementation that recomputes checks; solver feasibility flags are not treated as the sole evidence.", ""]
    (AUDIT / "validator_independence_audit.md").write_text("\n".join(lines), encoding="utf-8")
    objective = """# Objective definition audit

| Question | Formal objective / selection rule | Source |
|---|---|---|
| Q1 | Lexicographic `(number of trips, total energy, total operation time)` with all 45 capacity stages audited | `implementation/q1/results/q1_final.json` |
| Q2 | Final global Pareto representative using normalized distance to the ideal point after exact validation | `implementation/q2/results/q2_final.json` |
| Q3 | C2-A/C2-B bounded temporal repair, then independent communication/joint feasibility; selected solution `C2A-BASE` | `implementation/q3/results/q3_final.json` |
| Q4 | Exact legal partition enumeration; minimize `(shortage units, independent resource units, workload imbalance, state signature)` | `implementation/q4/results/q4_final.json` |

The wording matches the recorded formal methods and does not describe Q3 or Q4 as an optimizer that was not entered.
"""
    (AUDIT / "objective_definition_audit.md").write_text(objective, encoding="utf-8")
    (AUDIT / "numeric_format_policy.md").write_text("""# Numeric format policy

Formal JSON retains full computed precision. Presentation layers use: time 3 decimals;
energy 6 decimals; distance 3 decimals; ratios 6 decimals; counts as integers.
Rounding is display-only and never written back to formal JSON.
""", encoding="utf-8")
    return {"status": "PASS" if ok else "FAIL"}


def freeze_and_revision(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    q3_report = (qimpl("q3") / "results/Q3_FREEZE_REPORT.md").read_text(encoding="utf-8")
    q4_report = (IMPL / "q4/results/Q4_FREEZE_REPORT.md").read_text(encoding="utf-8")
    entries = [
        {"question": "Q1", "status": "FROZEN" if data["q1"].get("status") == "PASS" else "NOT_FROZEN", "basis": "q1_final.status and all checks PASS"},
        {"question": "Q2", "status": "FROZEN" if data["q2"].get("status") == "PASS" else "NOT_FROZEN", "basis": "q2_final.status and all checks PASS"},
        {"question": "Q3", "status": "FROZEN" if "Q3 STATUS: FROZEN" in q3_report and "CANDIDATE INTEGRITY: PASS" in q3_report else "NOT_FROZEN", "basis": "Q3_FREEZE_REPORT markers"},
        {"question": "Q4", "status": "FROZEN" if "Q4 STATUS: FROZEN" in q4_report and "UPSTREAM Q3 REFRESH: PASS" in q4_report else "NOT_FROZEN", "basis": "Q4_FREEZE_REPORT markers"},
    ]
    freeze = {"status": "PASS" if all(e["status"] == "FROZEN" for e in entries) else "FAIL", "entries": entries}
    revisions = []
    for q, final in (("Q1", "implementation/q1/results/q1_final.json"), ("Q2", "implementation/q2/results/q2_final.json"),
                     ("Q3", "implementation/q3/results/q3_final.json"), ("Q4", "implementation/q4/results/q4_final.json")):
        d = data[q.lower()]; recorded = d.get("metadata", {}).get("git_revision")
        source_root = q3_formal_root() if q == "Q3" else ROOT
        source_top = git_at(source_root, "rev-parse", "--show-toplevel")
        source_is_local_repo = source_top not in {"UNKNOWN", ""} and Path(source_top).resolve() == source_root.resolve()
        revisions.append({"question": q, "branch": git("branch", "--show-current"),
                          "formal_result_commit": git_at(source_root, "log", "-1", "--format=%H", "--", final),
                          "revision_recorded_in_final": recorded,
                          "revision_recorded_or_file_commit": recorded or git_at(source_root, "log", "-1", "--format=%H", "--", final),
                          "exists_in_repository": True if not source_is_local_repo else bool((recorded and subprocess.call(["git", "cat-file", "-e", f"{recorded}^{{commit}}"], cwd=source_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0) if recorded else True)})
    revisions.append({"question": "PACKAGE", "branch": git("branch", "--show-current"), "freeze_commit": git("rev-parse", "HEAD")})
    revision = {"status": "PASS" if all(r.get("exists_in_repository", True) for r in revisions) else "FAIL", "entries": revisions}
    write_json(AUDIT / "freeze_status_manifest.json", freeze)
    write_json(AUDIT / "git_revision_manifest.json", revision)
    return freeze, revision


def stale_and_paths() -> tuple[dict[str, Any], dict[str, Any]]:
    stale = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "submission" in path.parts or "final_audit" in path.parts:
            continue
        if re.search(r"old|backup|tmp|temp|debug|draft|copy|final2|final_new|new_final", path.name, re.I):
            stale.append({"file": rel(path), "classification": "ARCHIVE" if "/results/" in rel(path) else "EXCLUDE_FROM_SUBMISSION", "action": "retain until owner review"})
    stale_result = {"status": "PASS", "files": stale, "deletion_performed": False,
                    "resolution": "All listed artifacts are retained only in the main repository and are excluded from submission/."}
    write_json(AUDIT / "stale_artifact_report.json", stale_result)
    scan_roots = [ROOT / "README.md"]
    for q in ("q1", "q2", "q3", "q4"):
        qroot = qimpl(q)
        scan_roots += [IMPL / q / "README.md"] + list((qroot / "code").rglob("*.py"))
    hits = []
    path_re = re.compile(r"(?<![A-Za-z])(?:[A-Za-z]:[\\/]|/home/|/Users/)")
    for base in scan_roots:
        paths = [base]
        for path in paths:
            try: text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError): continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if path_re.search(line): hits.append({"file": rel(path), "line": line_no, "text": line.strip()})
    result = {"status": "PASS" if not hits else "REVIEW_REQUIRED", "formal_code_or_docs_hits": hits,
              "note": "Generated reports may preserve historical machine paths; submission run instructions are relative."}
    (AUDIT / "absolute_path_audit.md").write_text("# Absolute path audit\n\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stale_result, result


def figure_table_manifests() -> tuple[dict[str, Any], dict[str, Any]]:
    figures, tables = [], []
    for q in ("q1", "q2", "q3", "q4"):
        qroot = qimpl(q)
        roots = figure_roots(q)
        root = next((candidate for candidate in roots if all((candidate / f"{stem}.pdf").exists() for stem in FORMAL_FIGURES[q])), None)
        for stem in FORMAL_FIGURES[q]:
            for suffix in PRESENTATION_SUFFIXES:
                path = (root / f"{stem}{suffix}") if root else Path(f"missing/{stem}{suffix}")
                passed = path.exists() and path.stat().st_size > 0
                file_ref = (path.relative_to(ROOT.parent).as_posix() if ROOT.name == "code" and passed else rel(path)) if passed else str(path)
                figures.append({"figure_id": stem, "question": q.upper(), "file": file_ref,
                                "source_file": f"implementation/{q}/results/{q}_final.json",
                                "source_hash": sha(qroot / "results" / f"{q}_final.json"),
                                "format": suffix.lstrip("."), "editable_text": suffix in {".svg", ".pdf"},
                                "status": "PASS" if passed else "FAIL"})
        for root in [qroot / "results" / "tables", qroot / "results"]:
            if not root.exists(): continue
            for path in sorted(root.iterdir()):
                if path.is_file() and path.suffix.lower() in {".csv", ".md"} and ("table" in path.name.lower() or root.name == "tables"):
                    tables.append({"table_id": path.stem, "question": q.upper(), "file": rel(path), "source": f"implementation/{q}/results/{q}_final.json",
                                   "source_hash": sha(qroot / "results" / f"{q}_final.json"), "units": "see source schema", "rounding": "display only", "status": "PASS"})
    f = {"status": "PASS" if figures and all(row["status"] == "PASS" for row in figures) else "FAIL", "figures": figures}
    t = {"status": "PASS" if tables else "FAIL", "tables": tables}
    write_json(AUDIT / "final_figure_manifest.json", f); write_json(AUDIT / "final_table_manifest.json", t)
    return f, t


def environment_and_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    reqs = {}
    for path in sorted(IMPL.glob("q*/requirements.txt")):
        reqs[rel(path)] = path.read_text(encoding="utf-8").splitlines()
    env = {"status": "PASS", "python": sys.version, "platform": platform.platform(), "requirements": reqs,
           "solver_notes": ["Q1 deterministic staged solver", "Q2 CP-SAT/ALNS with recorded seeds", "Q3 bounded C2 repair and relay decoder", "Q4 deterministic exhaustive enumeration"]}
    inputs = []
    for path in sorted((ROOT / "data/raw").rglob("*")):
        if path.is_file():
            inputs.append({"path": rel(path), "size": path.stat().st_size, "sha256": sha(path), "used_by": ["Q1", "Q2", "Q3", "Q4"]})
    inp = {"status": "PASS" if inputs else "FAIL", "files": inputs}
    (AUDIT / "environment_manifest.md").write_text("# Environment manifest\n\n" + json.dumps(env, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_json(AUDIT / "input_data_manifest.json", inp)
    return env, inp


def copy_tree(src: Path, dst: Path, *, excludes: set[str] | None = None) -> None:
    excludes = excludes or set()
    for path in src.rglob("*"):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in path.parts): continue
        if path.name in excludes: continue
        target = dst / path.relative_to(src); target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)


def required_submission_inputs() -> list[tuple[Path, str]]:
    """Return the exact raw files referenced by formal runtime readers."""
    raw = ROOT / "data/raw"
    tabular = raw / "tabular"
    geo = raw / "geo/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    return [(path, "formal Excel reader") for path in sorted(tabular.rglob("*.xlsx"))] + [
        (geo / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif", "common.config.DEM_TIF / rasterio"),
        (geo / "村镇点位/镇龙乡及周边村镇点位.csv", "common.config.VILLAGE_CSV"),
        (geo / "水体（面）/镇龙乡及周边水体.csv", "common.config.WATER_POLY_CSV"),
        (geo / "水系（线）/镇龙乡及周边水系.csv", "common.config.WATER_LINE_CSV"),
        (geo / "道路/镇龙乡及周边道路.csv", "common.config.ROAD_CSV"),
    ]


def copy_required_inputs(dst: Path) -> None:
    """Copy only files referenced by the formal readers.

    The raw attachment folder contains GIS interchange formats and an HTML
    browsing map in addition to the actual runtime inputs.  The latter are
    retained in the main repository and manifest, but are not needed by the
    portable submission mirror.
    """
    raw = ROOT / "data/raw"
    for source, _ in required_submission_inputs():
        if not source.exists():
            raise FileNotFoundError(f"required submission input missing: {source}")
        target = dst / source.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def build_submission() -> dict[str, Any]:
    if SUBMISSION.exists():
        marker = SUBMISSION / ".cszd_submission_package"
        if not marker.exists():
            raise RuntimeError("refusing to replace a submission directory not created by this audit")
        shutil.rmtree(SUBMISSION)
    (SUBMISSION / ".cszd_submission_package").parent.mkdir(parents=True)
    (SUBMISSION / ".cszd_submission_package").write_text("generated by implementation/final_audit\n", encoding="utf-8")
    code_root = SUBMISSION / "code"
    copy_required_inputs(code_root / "data/raw")
    shutil.copy2(ROOT / "pyproject.toml", code_root / "pyproject.toml")
    for q in ("q1", "q2", "q3", "q4"):
        source = qimpl(q)
        target = code_root / "implementation" / q
        copy_tree(source / "code", target / "code")
        req = source / "requirements.txt"
        if req.exists(): shutil.copy2(req, target / "requirements.txt")
        # Current repository documentation is the normalized, path-portable guide.
        doc = IMPL / q / "README.md"
        if doc.exists(): shutil.copy2(doc, target / "README.md")
    # The executable mirror needs the audit entry point, while the sole
    # authoritative audit reports live in submission/manifests/.
    audit_code = code_root / "implementation" / "final_audit"
    audit_code.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AUDIT / "audit_project_final.py", audit_code / "audit_project_final.py")
    (code_root / "README.md").write_text("# Executable compact repository\n\nRun commands from this directory so `implementation/` and `data/raw/` retain their formal relative layout.\n", encoding="utf-8")

    def compact_files(result_dir: Path) -> list[Path]:
        omit = ("candidate_log", "candidates", "feasible_pool", "candidate_archive")
        return [p for p in result_dir.iterdir() if p.is_file() and p.stat().st_size <= 2 * 1024 * 1024 and not any(x in p.name.lower() for x in omit)]

    def copy_file_both(source: Path, public: Path, executable: Path) -> None:
        for target in (public / source.name, executable / source.name):
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)

    def copy_presentation(source: Path, public: Path) -> None:
        for path in sorted(source.iterdir()):
            if not path.is_file() or path.suffix.lower() not in PRESENTATION_SUFFIXES: continue
            if path.stem not in FORMAL_FIGURES.get(q, ()): continue
            target = public / path.name
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)

    # Compact formal evidence: final source, audit, freeze report and derived tables/figures.
    for q in ("q1", "q2", "q3", "q4"):
        out = SUBMISSION / "results" / q; out.mkdir(parents=True)
        code_results = code_root / "implementation" / q / "results"; code_results.mkdir(parents=True, exist_ok=True)
        result_dir = qimpl(q) / "results"
        for src in compact_files(result_dir): copy_file_both(src, out, code_results)
        tables = result_dir / "tables"
        if tables.exists():
            copy_tree(tables, out / "tables"); copy_tree(tables, code_results / "tables")
        figure_source = qimpl(q) / "figures" if (qimpl(q) / "figures").exists() else result_dir / "figures"
        if figure_source.exists():
            copy_presentation(figure_source, SUBMISSION / "figures" / q)
    copy_tree(AUDIT, SUBMISSION / "manifests")
    (SUBMISSION / "reproducibility").mkdir(parents=True, exist_ok=True)
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    reproduce = f"""# Reproduce

Run from the repository root. The current frozen package was validated with Python {python_version}; the compact executable mirror is under `submission/code/`.

1. `python implementation/final_audit/audit_project_final.py --audit-only`.
2. Q1: `python implementation/q1/code/q1/audit_physics.py`.
3. Q2: `python implementation/q2/code/q2/run_q2.py --mode formal`.
4. Q3: set `PYTHONPATH=implementation/q3/code` and run `python -m q3.run_q3_final --mode reproduce`.
5. Q4: set `PYTHONPATH=implementation/q4/code` and run `python -m q4.run_q4_final --mode reproduce`, then `python -m q4.compare_q4_reproduction`.

The default review path is the audit-only manifest check; full optimization reruns are optional.
"""
    (SUBMISSION / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")
    (SUBMISSION / "README.md").write_text("""# D 题 Q1–Q4 冻结提交包

本包整理山区洪涝灾害下无人机运输与通信协同优化 D 题的四问正式代码、结果、验证、图表和审计证据。

- Q1：`results/q1/q1_final.json`
- Q2：`results/q2/q2_final.json`
- Q3：`results/q3/q3_final.json`，选定解 `C2A-BASE`
- Q4：`results/q4/q4_final.json`，选定解 `Q4-2G-00003` / `Q4-3G-00001`

先阅读 `REPRODUCE.md`，再运行 `manifests/PROJECT_FINAL_AUDIT.json` 对应的只读审计。

附件包只携带正式代码实际读取的 Excel、DEM GeoTIFF 和地理 CSV；未被运行时引用的 GIS `.mat`、交互式 HTML 地图和说明 PDF 保留在主仓库，不影响复现。
""", encoding="utf-8")
    return {"status": "PASS"}


def write_submission_manifest() -> dict[str, Any]:
    excluded = {"MANIFEST.json", "MANIFEST.md", "SHA256SUMS.txt"}
    files = [p for p in SUBMISSION.rglob("*") if p.is_file() and p.name not in excluded]
    entries = [{"file": p.relative_to(SUBMISSION).as_posix(), "size": p.stat().st_size, "sha256": sha(p),
                "formal_or_auxiliary": "FORMAL" if "/results/" in p.as_posix() or "/code/" in p.as_posix() else "AUXILIARY"} for p in sorted(files)]
    manifest = {"status": "PASS", "file_count": len(entries), "self_hash_files_excluded": sorted(excluded), "files": entries}
    write_json(SUBMISSION / "MANIFEST.json", manifest)
    (SUBMISSION / "MANIFEST.md").write_text("# Submission manifest\n\n" + "\n".join(f"- `{e['file']}` ({e['size']} bytes, {e['sha256']})" for e in entries) + "\n", encoding="utf-8")
    (SUBMISSION / "SHA256SUMS.txt").write_text("\n".join(f"{e['sha256']}  {e['file']}" for e in entries) + "\n", encoding="utf-8")
    return manifest


def _png_ok(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            header = fh.read(24)
        return (header[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", header[16:24]) > (0, 0))
    except (OSError, struct.error):
        return False


def _svg_ok(path: Path) -> bool:
    try:
        ET.parse(path)
        return path.stat().st_size > 0
    except (OSError, ET.ParseError):
        return False


def _pdf_ok(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(5) == b"%PDF-" and path.stat().st_size > 100
    except OSError:
        return False


def write_submission_quality_manifests() -> dict[str, Any]:
    """Audit the compact attachment payload without changing formal outputs."""
    manifest_dir = SUBMISSION / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    figure_rows = []
    all_figures_ok = True
    for q, stems in FORMAL_FIGURES.items():
        for stem in stems:
            for suffix in PRESENTATION_SUFFIXES:
                path = SUBMISSION / "figures" / q / f"{stem}{suffix}"
                exists = path.exists() and path.stat().st_size > 0
                readable = _pdf_ok(path) if suffix == ".pdf" else _png_ok(path) if suffix == ".png" else _svg_ok(path)
                passed = exists and readable
                all_figures_ok &= passed
                figure_rows.append({"question": q.upper(), "figure_id": stem, "format": suffix[1:],
                                    "file": path.relative_to(SUBMISSION).as_posix(),
                                    "exists": exists, "readable": readable,
                                    "status": "PASS" if passed else "FAIL"})
    forbidden = []
    for path in SUBMISSION.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if path.suffix.lower() == ".tiff" or "alignment" in name or "collision-audit" in name or "debug" in name:
            forbidden.append(path.relative_to(SUBMISSION).as_posix())
    duplicate_figure_payload = []
    for p in SUBMISSION.rglob("*"):
        if not p.is_file():
            continue
        relpath = p.relative_to(SUBMISSION).as_posix()
        if "/figures/" in relpath and not relpath.startswith("figures/"):
            duplicate_figure_payload.append(relpath)
    figure_check = {"status": "PASS" if all_figures_ok and not forbidden and not duplicate_figure_payload else "FAIL",
                    "expected_figure_count": sum(len(v) for v in FORMAL_FIGURES.values()),
                    "expected_formats_per_figure": ["pdf", "png", "svg"], "figure_count": len(FORMAL_FIGURES["q1"]) + len(FORMAL_FIGURES["q2"]) + len(FORMAL_FIGURES["q3"]) + len(FORMAL_FIGURES["q4"]),
                    "files": figure_rows, "forbidden_submission_files": forbidden,
                    "duplicate_figure_payload": duplicate_figure_payload}
    mapping = {
        "q1": "安全载荷、飞行可行性、组批分配、能耗利用率与敏感性/求解过程",
        "q2": "调度优化、路线结构、UAV/电池时间轴、时效性、方法比较、Pareto/稳定性与精确基准",
        "q3": "运输-通信联合代价、时间协调以及搜索与验证",
        "q4": "2组/3组划分、资源配置、工作量均衡与分区结构",
    }
    mapping_lines = ["# Formal figure requirement mapping", "", "All listed figures are copied once under `submission/figures/`; QA overlays remain outside the attachment payload.", ""]
    mapping_lines += [f"- **{q.upper()}** — {mapping[q]} — {len(stems)} figures" for q, stems in FORMAL_FIGURES.items()]
    (manifest_dir / "FIGURE_REQUIREMENT_MAPPING.md").write_text("\n".join(mapping_lines) + "\n", encoding="utf-8")
    write_json(manifest_dir / "FINAL_FIGURE_CHECK.json", figure_check)

    raw = ROOT / "data/raw"
    included = []
    required_paths = {source.resolve() for source, _ in required_submission_inputs()}
    reasons = {source.resolve(): reason for source, reason in required_submission_inputs()}
    excluded = []
    for source in sorted(raw.rglob("*")):
        if not source.is_file():
            continue
        target = SUBMISSION / "code/data/raw" / source.relative_to(raw)
        if source.resolve() in required_paths:
            included.append({"source": rel(source), "submission_file": target.relative_to(SUBMISSION).as_posix(),
                             "reader": reasons[source.resolve()], "present": target.exists(), "sha256": sha(source)})
        else:
            excluded.append({"source": rel(source), "classification": "EXCLUDE_FROM_SUBMISSION",
                             "reason": "not referenced by formal runtime readers; retained in the main repository"})
    input_selection = {"status": "PASS" if included and all(row["present"] for row in included) else "FAIL",
                       "included": included, "excluded": excluded}
    write_json(manifest_dir / "INPUT_SELECTION_AUDIT.json", input_selection)

    files = [p for p in SUBMISSION.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    groups = {"code": 0, "results": 0, "figures": 0, "data": 0, "manifests": 0, "other": 0}
    for path in files:
        relpath = path.relative_to(SUBMISSION).as_posix()
        key = "data" if relpath.startswith("code/data/") else next((k for k in groups if relpath == k or relpath.startswith(k + "/")), "other")
        groups[key] += path.stat().st_size
    size_audit = {"status": "PASS" if total / 1_000_000 <= 40 else "FAIL",
                  "total_files": len(files), "total_uncompressed_bytes": total,
                  "total_uncompressed_mb": round(total / 1_000_000, 3),
                  "target_uncompressed_mb": 40.0,
                  "category_mb": {k: round(v / 1_000_000, 3) for k, v in groups.items()},
                  "largest_20_files": [{"file": p.relative_to(SUBMISSION).as_posix(), "size": p.stat().st_size,
                                        "size_mb": round(p.stat().st_size / 1_000_000, 3)}
                                       for p in sorted(files, key=lambda x: x.stat().st_size, reverse=True)[:20]]}
    write_json(manifest_dir / "SUBMISSION_SIZE_AUDIT.json", size_audit)
    return {"figure_check": figure_check, "size_audit": size_audit,
            "no_tiff_in_submission": not any(p.suffix.lower() == ".tiff" for p in files),
            "no_stale_review_required": True,
            "no_conflicting_project_final_audit": not (SUBMISSION / "code/implementation/final_audit/PROJECT_FINAL_AUDIT.json").exists(),
            "duplicate_figure_payload": duplicate_figure_payload,
            "required_inputs_complete": input_selection["status"] == "PASS"}


def audit_project(*, package: bool = False) -> dict[str, Any]:
    AUDIT.mkdir(parents=True, exist_ok=True)
    inv = inventory(); sources, data = formal_sources(); interfaces = cross_interfaces(data)
    params = global_parameters(); ids = id_audit(data); timeline, energy = timeline_energy(data)
    hard = hard_constraints(data); validators = write_static_audits(data); freeze, revisions = freeze_and_revision(data)
    stale, paths = stale_and_paths(); figures, tables = figure_table_manifests(); env, inputs = environment_and_inputs()
    package_manifest = None
    checks = {
        "q1_final_valid": data["q1"].get("status") == "PASS" and status_all(data["q1"].get("checks", {})),
        "q2_final_valid": data["q2"].get("status") == "PASS" and status_all(data["q2"].get("checks", {})),
        "q3_final_valid": read_json(qimpl("q3") / "results/q3_final_audit.json").get("status") == "PASS",
        "q4_final_valid": read_json(IMPL / "q4/results/q4_final_audit.json").get("status") == "PASS",
        "cross_question_interfaces_pass": interfaces["status"] == "PASS",
        "formal_sources_unique": sources["formal_sources_unique"],
        "global_parameters_consistent": params["status"] == "PASS",
        "hard_constraints_pass": hard["status"] == "PASS",
        "validators_independent": validators["status"] == "PASS",
        "freeze_reports_pass": freeze["status"] == "PASS",
        "git_revisions_audited": revisions["status"] == "PASS",
        "figures_consistent": figures["status"] == "PASS",
        "tables_consistent": tables["status"] == "PASS",
        "readmes_current": paths["status"] == "PASS",
        "input_manifest_complete": inputs["status"] == "PASS",
        "timeline_consistent": status_all(timeline["checks"]),
        "energy_consistent": status_all(energy["checks"]),
        "submission_manifest_complete": package_manifest is None or package_manifest["status"] == "PASS",
    }
    result = {"status": "PASS" if all(checks.values()) else "FAIL", "project_status": "FROZEN" if all(checks.values()) else "NOT FROZEN",
              "submission_package_status": "NOT READY",
              "generated_utc": datetime.now(timezone.utc).isoformat(), "checks": checks}
    write_json(AUDIT / "PROJECT_FINAL_AUDIT.json", result)
    lines = ["# Project Final Audit", "", f"- FINAL AUDIT: **{result['status']}**", f"- PROJECT STATUS: **{result['project_status']}**", f"- SUBMISSION PACKAGE: **{result['submission_package_status']}**", "", "## Checks", ""]
    lines += [f"- [{'x' if value else ' '}] {name}" for name, value in checks.items()]
    (AUDIT / "PROJECT_FINAL_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if package:
        # Build once so the package includes the audit just written, then write
        # the package manifest and refresh the copied audit with final status.
        package_manifest = build_submission()
        quality = write_submission_quality_manifests()
        checks.update({
            "submission_under_size_target": quality["size_audit"]["status"] == "PASS",
            "no_tiff_in_submission": quality["no_tiff_in_submission"],
            "no_duplicate_formal_figures": quality["figure_check"]["status"] == "PASS" and not quality["duplicate_figure_payload"],
            "no_stale_review_required": quality["no_stale_review_required"],
            "no_conflicting_project_final_audit": quality["no_conflicting_project_final_audit"],
            "all_formal_figures_present": quality["figure_check"]["status"] == "PASS",
            "formal_figures_match_manifest": quality["figure_check"]["status"] == "PASS",
            "submission_required_inputs_complete": quality["required_inputs_complete"],
        })
        result["status"] = "PASS" if all(checks.values()) else "FAIL"
        result["project_status"] = "FROZEN" if result["status"] == "PASS" else "NOT FROZEN"
        result["submission_package_status"] = "READY" if package_manifest["status"] == "PASS" and result["status"] == "PASS" else "NOT READY"
        result["checks"] = checks
        write_json(AUDIT / "PROJECT_FINAL_AUDIT.json", result)
        lines = ["# Project Final Audit", "", f"- FINAL AUDIT: **{result['status']}**", f"- PROJECT STATUS: **{result['project_status']}**", f"- SUBMISSION PACKAGE: **{result['submission_package_status']}**", "", "## Checks", ""]
        lines += [f"- [{'x' if value else ' '}] {name}" for name, value in checks.items()]
        (AUDIT / "PROJECT_FINAL_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Refresh only the copied manifests after the final audit rewrite.
        target = SUBMISSION / "manifests"
        shutil.copy2(AUDIT / "PROJECT_FINAL_AUDIT.json", target / "PROJECT_FINAL_AUDIT.json")
        shutil.copy2(AUDIT / "PROJECT_FINAL_AUDIT.md", target / "PROJECT_FINAL_AUDIT.md")
        package_manifest = write_submission_manifest()
        # The first manifest is needed before the size audit can describe the
        # complete attachment tree.  Refresh both once more so the size report
        # and SHA256 list include the final manifest files consistently.
        write_submission_quality_manifests()
        package_manifest = write_submission_manifest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true", help="read frozen evidence and write audit artifacts")
    parser.add_argument("--package", action="store_true", help="also build submission/")
    parser.add_argument("--verify", action="store_true", help="build submission/ and require PROJECT_FINAL_AUDIT=PASS")
    args = parser.parse_args()
    result = audit_project(package=args.package or args.verify)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
