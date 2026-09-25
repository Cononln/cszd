# Objective definition audit

| Question | Formal objective / selection rule | Source |
|---|---|---|
| Q1 | Lexicographic `(number of trips, total energy, total operation time)` with all 45 capacity stages audited | `implementation/q1/results/q1_final.json` |
| Q2 | Final global Pareto representative using normalized distance to the ideal point after exact validation | `implementation/q2/results/q2_final.json` |
| Q3 | C2-A/C2-B bounded temporal repair, then independent communication/joint feasibility; selected solution `C2A-BASE` | `implementation/q3/results/q3_final.json` |
| Q4 | Exact legal partition enumeration; minimize `(shortage units, independent resource units, workload imbalance, state signature)` | `implementation/q4/results/q4_final.json` |

The wording matches the recorded formal methods and does not describe Q3 or Q4 as an optimizer that was not entered.
