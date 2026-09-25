# Q4 Freeze Report

## Upstream inheritance

- Q3 solution: `C2A-BASE`
- Q4 reads only the selected Q3 formal solution.

## Formal method

Enumerate all unlabeled nonempty partitions of frozen multi-stop service-area components for k=2 and k=3.

## Selected configurations

| Groups | Solution | Resource units | Shortage units | Workload imbalance |
|---:|---|---:|---:|---:|
| 2 | `Q4-2G-00003` | 33 | 3 | 12.276880 |
| 3 | `Q4-3G-00001` | 37 | 7 | 12.120035 |

## Search

- 2 groups: 1023 legal unique candidates; 1023 validator PASS
- 3 groups: 28501 legal unique candidates; 28501 validator PASS

## Freeze checks

- [x] Q3 interface
- [x] variable legality
- [x] independent validator
- [x] hard constraints
- [x] candidate integrity
- [x] feasible pool
- [x] final audit
- [x] figures and tables
- [x] clean reproduction
- [x] Q3 frozen files

Q4 STATUS: FROZEN
