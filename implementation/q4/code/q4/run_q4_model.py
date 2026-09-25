"""Q4-A/B baseline and exact finite partition search."""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

from .q4_model import canonical_q4_state_signature, enumerate_partitions, evaluate_partition, prepare_state
from .q3_adapter import results_root
from .validate_q4 import validate_candidate


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate(prepared: dict[str, Any], groups, candidate_id: str, operator: str) -> dict[str, Any]:
    row = evaluate_partition(prepared, groups, candidate_id=candidate_id,
                             parent_id=prepared["interface"]["selected_solution_id"], operator=operator)
    validation = validate_candidate(row, prepared)
    row["validator_status"] = "PASS" if validation["status"] == "PASS" else "FAIL"
    row["validator_result"] = validation
    return row


def _chunked(items: list[Any], n: int) -> list[list[Any]]:
    return [items[index::n] for index in range(n) if items[index::n]]


def _evaluate_chunks(prepared: dict[str, Any], partitions: list[Any], n_groups: int) -> list[dict[str, Any]]:
    indexed = list(enumerate(partitions))
    chunks = _chunked(indexed, 4)
    def evaluate_chunk(chunk: list[tuple[int, Any]]) -> list[dict[str, Any]]:
        return [_candidate(prepared, groups, f"Q4-{n_groups}G-{index:05d}",
                           f"partition_{n_groups}groups")
                for index, groups in chunk]
    with ThreadPoolExecutor(max_workers=min(4, len(chunks)), thread_name_prefix=f"q4-{n_groups}g") as pool:
        nested = [future.result() for future in [pool.submit(evaluate_chunk, chunk) for chunk in chunks]]
    rows = [row for sublist in nested for row in sublist]
    return sorted(rows, key=lambda row: row["candidate_id"])


def _candidate_evidence(row: dict[str, Any]) -> dict[str, Any]:
    return {"candidate_id": row["candidate_id"], "parent_id": row["parent_id"], "operator": row["operator"],
            "n_groups": row["n_groups"], "state_signature": row["state_signature"],
            "changed_variables": row["changed_variables"], "unchanged_frozen_variables": row["unchanged_frozen_variables"],
            "upstream_q3_reference": row["upstream_q3_reference"],
            "objective": row["objective"], "shortages": row["shortages"],
            "hard_constraint_checks": row["hard_constraint_checks"], "validator_status": row["validator_status"]}


def _objective_key(row: dict[str, Any]) -> tuple[Any, ...]:
    objective = row["objective"]
    return (objective["total_shortage_units"], objective["total_resource_units"],
            objective["imbalance_ratio"], row["state_signature"])


def _failure_taxonomy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    failures = []
    for row in rows:
        if row["validator_status"] == "PASS":
            continue
        category = "Q4_NEW_COUPLING_VIOLATION" if not row["hard_constraint_checks"].get("multi_stop_trips_single_group", True) else "Q4_VALIDATOR_FAILURE"
        counts[category] = counts.get(category, 0) + 1
        failures.append({"candidate_id": row["candidate_id"], "state_signature": row["state_signature"],
                         "category": category, "source_check": "independent_q4_validator", "source_value": False})
    return {"counts": dict(sorted(counts.items())), "candidate_failures": failures}


def run_model() -> dict[str, Any]:
    root = results_root()
    prepared = prepare_state()
    interface = prepared["interface"]
    components = prepared["components"]
    baseline_groups = (tuple(range(len(components))),)
    baseline = _candidate(prepared, baseline_groups, "Q4-BASE-ALL", "unpartitioned_q3_reference")
    _json(root / "q4_baseline.json", baseline)
    _json(root / "q4_baseline_validation.json", baseline["validator_result"])
    baseline_report = ("# Q4 Baseline\n\n"
                       f"- upstream Q3 solution: `{interface['selected_solution_id']}`\n"
                       f"- baseline validator: **{baseline['validator_status']}**\n"
                       f"- total resource units: {baseline['objective']['total_resource_units']}\n"
                       f"- total shortage units: {baseline['objective']['total_shortage_units']}\n")
    (root / "q4_baseline_report.md").write_text(baseline_report, encoding="utf-8")
    search_started = perf_counter()
    all_rows: list[dict[str, Any]] = []
    summaries = {}
    for n_groups in (2, 3):
        partitions = enumerate_partitions(len(components), n_groups)
        rows = _evaluate_chunks(prepared, partitions, n_groups)
        signatures = [row["state_signature"] for row in rows]
        feasible = [row for row in rows if row["validator_status"] == "PASS"]
        selected = min(feasible, key=_objective_key) if feasible else None
        summaries[str(n_groups)] = {"generated_raw_count": len(partitions), "noop_removed_count": 0,
                                    "duplicate_removed_count": len(rows) - len(set(signatures)),
                                    "unique_candidate_count": len(set(signatures)),
                                    "candidate_count": len(rows), "feasible_count": len(feasible),
                                    "selected_solution_id": selected["candidate_id"] if selected else None,
                                    "selected_state_signature": selected["state_signature"] if selected else None,
                                    "status": "PASS" if selected else "UNRESOLVED"}
        all_rows.extend(rows)
        _json(root / f"q4_{n_groups}group_candidates.json", {"n_groups": n_groups, **summaries[str(n_groups)],
                                                                 "candidates": [_candidate_evidence(row) for row in rows]})
    signatures = [row["state_signature"] for row in all_rows]
    feasible = [row for row in all_rows if row["validator_status"] == "PASS"]
    csv_rows = []
    for row in all_rows:
        csv_rows.append({"candidate_id": row["candidate_id"], "n_groups": row["n_groups"], "state_signature": row["state_signature"],
                         "validator_status": row["validator_status"], **row["objective"],
                         "group_service_areas": json.dumps([group["service_areas"] for group in row["groups"]], ensure_ascii=False)})
    with (root / "q4_candidate_log.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0]))
        writer.writeheader(); writer.writerows(csv_rows)
    failures = _failure_taxonomy(all_rows)
    _json(root / "q4_failure_taxonomy.json", failures)
    selected = {str(n): min([row for row in all_rows if row["n_groups"] == n and row["validator_status"] == "PASS"],
                            key=_objective_key) for n in (2, 3)}
    pool = [{"solution_id": row["candidate_id"], "parent_id": row["parent_id"], "state_signature": row["state_signature"],
             "operator": row["operator"], "stage": "Q4-D", "upstream_q3_reference": row["upstream_q3_reference"],
             "decision_variables": row["changed_variables"], "unchanged_frozen_variables": row["unchanged_frozen_variables"],
             "derived_metrics": {"resource_requirements": row["resource_requirements"],
             "shortages": row["shortages"], "workload": row["workload"]},
             "objective": row["objective"], "hard_constraint_checks": row["hard_constraint_checks"], "validator_status": row["validator_status"]}
            for row in feasible]
    _json(root / "q4_feasible_pool.json", {"source": "q4_final.json", "solutions": pool})
    elapsed = perf_counter() - search_started
    return {"prepared": prepared, "baseline": baseline, "summaries": summaries, "all_rows": all_rows,
            "feasible": feasible, "selected": selected, "pool": pool, "failure_taxonomy": failures,
            "search_runtime_s": elapsed, "candidate_state_signatures_unique": len(signatures) == len(set(signatures))}
