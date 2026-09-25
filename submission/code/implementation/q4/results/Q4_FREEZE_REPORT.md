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

## Q3 upstream refresh

- old Q3 formal revision: `94154eb01e06a40abb5df8a4d1044019b92ae7b3`
- latest Q3 formal revision: `c7880a36e1f5e9efb39f0d6d6be9d38b9638d80a`
- Q3 refreeze commit: `35a5668e9822dc92c2d8c8a21bbd01f1452ba487`
- selected solution: `C2A-BASE`
- transport state unchanged: PASS
- transport schedule unchanged: PASS
- relay schedule unchanged: FAIL
- core objectives unchanged: PASS
- Q4 re-enumeration required: YES
- Q4 re-enumeration completed: YES

## Freeze checks

- [x] Q3 interface
- [x] variable legality
- [x] independent validator
- [x] hard constraints
- [x] candidate integrity
- [x] feasible pool
- [x] final audit
- [x] figures and tables
- [x] Q3 upstream refresh
- [x] clean reproduction
- [x] Q3 frozen files

Q4 STATUS: FROZEN
UPSTREAM Q3 REFRESH: PASS
