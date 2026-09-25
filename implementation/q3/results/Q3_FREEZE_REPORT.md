# Q3 Freeze Report

## 1. Final method

The formal Q3 pipeline uses frozen Q2 routes, C2-A constrained temporal repair, bounded C2-B combinations, the real Q3-B relay decoder, independent transport/relay/joint validators, and a final source-consistency audit.

## 2. C2-A result

- status: **PASS**
- raw candidates generated: 9
- no-op candidates removed: 4
- duplicate decision states removed: 0
- unique candidates: 5
- joint-feasible candidates: 4

## 3. C2-B result

- status: **PASS**
- raw combinations generated: 4
- no-op combinations removed: 2
- duplicate decision states removed: 0
- unique combinations: 2
- joint-feasible candidates: 1

## 4. Final solution

- solution id: `C2A-BASE`
- repair stage: `C2-A`
- fleet configuration: `{"A": 9, "B": 9, "C": 7}`

## 5. Objective values

| Metric | Value |
|---|---:|
| WTD | 2919779.443347 |
| Transport Cmax (s) | 23738.870393 |
| Joint Cmax (s) | 24147.775014 |
| Transport energy (kWh) | 70.118168 |
| Relay energy (kWh) | 8.247977 |
| Total energy (kWh) | 78.366144 |
| Transport trips | 25 |
| Relay sorties | 6 |

## 6. Hard constraints and validator

- independent validation: **PASS**
- full communication outage: 0 s
- source-number consistency: **PASS**

## 7. Final audit

| Check | Status |
|---|---|
| q2_frozen_files_untouched | PASS |
| independent_validator_pass | PASS |
| all_hard_constraints_pass | PASS |
| full_communication_zero_outage | PASS |
| source_numbers_consistent | PASS |
| schedule_csv_complete | PASS |
| no_formal_optimizer_entered | PASS |
| single_formal_source_declared | PASS |
| failure_taxonomy_present | PASS |
| no_noop_candidates | PASS |
| candidate_state_signatures_unique | PASS |
| feasible_pool_state_signatures_unique | PASS |
| candidate_counts_recomputed | PASS |
| failure_taxonomy_semantically_valid | PASS |
| formal_figure_manifest_present | PASS |
| formal_table_manifest_present | PASS |
| figures_read_only_q3_final | PASS |
| tables_read_only_q3_final | PASS |
| figure_qa_pass | PASS |
| all_manifest_artifacts_present | PASS |

## 7A. Candidate integrity

- no-op candidates: 0
- duplicate decision states: 0
- feasible-pool duplicate states: 0

## 8. Clean run

- status: **PASS**
- selected solution reproduced: `C2A-BASE`

## 9. Formal files

- `results/q3_final.json` — unique formal numeric source
- `results/q3_final_audit.json` — independent final audit
- `results/q3_feasible_pool.json` and `results/q3_failure_taxonomy.json`
- `results/figures/` — SVG, PDF, TIFF, alignment and collision QA
- `results/tables/` — CSV and Markdown tables
- `reproducibility/clean_results/` — clean-run evidence

## 10. Figures

- Fig_Q3_01_joint_solution_cost: solution resource cost
- Fig_Q3_02_temporal_coordination: transport/relay temporal replay
- Fig_Q3_03_search_validation: bounded search and failure taxonomy

## 11. Git

- revision recorded in q3_final: `c7880a36e1f5e9efb39f0d6d6be9d38b9638d80a`
- freeze commit message: `Freeze Q3 validated reproducible solution`

## 12. Freeze checklist

- [x] C2-A complete
- [x] C2-B complete
- [x] validator PASS
- [x] final audit PASS
- [x] figures PASS
- [x] tables PASS
- [x] clean run PASS
- [x] Q2 frozen
- [x] single formal source
- [x] no formal optimizer
- [x] all deliverables present
- [x] candidate integrity PASS

Q3 STATUS: FROZEN
CANDIDATE INTEGRITY: PASS
