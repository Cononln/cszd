# Q2 publication-quality figure report

## Numerical gate
- q2_final.status = PASS
- run_mode = formal
- formal_solution_id = `seed-20260930-iter-0`
- exact OPTIMAL instances = 2
- Gate E = PASS
- q2_solution_boxes rows = 80

## Figure contract
- Core conclusion: the formal ALNS schedule is feasible, Pareto-screened, and materially exploits multi-stop transport while satisfying shared-resource replay checks.
- Archetype: quantitative grid plus route/timeline validation figures.
- Hero evidence: final Pareto selection, route structure and UAV timeline.
- Supporting evidence: exact benchmark, delivery timeliness, battery reuse and operator audit.

## Provenance and constraints
- Q2 numerical solver files modified = NO
- Q2 physics files modified = NO
- Figures generated from formal results = YES
- Font selected: `Microsoft YaHei` (editable SVG text; Arial/DejaVu fallback configured).
- No manual CSV/JSON values were inserted or edited by the plotting script.
- A/B plotting assets were used only for chart-structure inspiration; Q2 values come from the formal result files.

## QA notes
- PDF, SVG and 600-dpi PNG exported for every figure.
- Alignment JSON/SVG emitted for each figure; multi-panel layouts use the 1.5 pt strict gate.
- Current bundle: all ten PDF text audits and all ten rendered collision audits PASS (0 FAIL, 0 WARN).
- Source validator: 18 PASS, 3 documented WARN, 0 FAIL; WARNs are TIFF omission, non-default composite width, and raw seed points without uncertainty bands.
- Small-3 exact benchmark remains FEASIBLE/unresolved and is not shown as an exact gap.

## Source files
- implementation/q2/results/q2_final.json
- implementation/q2/results/q2_method_comparison.csv
- implementation/q2/results/q2_pareto.csv and q2_candidate_archive.csv
- implementation/q2/results/q2_multiseed.csv and q2_exact_validation.csv
- implementation/q2/results/q2_solution_*.csv, q2_battery_*.csv, q2_multistop_audit.csv, q2_operator_stats.csv
