# Q3-B Joint Relay Decoder

## 1. Decoder validation

- decoder status: **PASS**
- decoder validation status: **PASS**
- option-space enumeration: complete continuous windows

## 2. Q2 formal baseline result

- baseline status: **INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET**
- solver status: `INFEASIBLE`
- all_demands_candidate_coverable: PASS
- all_demands_scheduled_covered: FAIL
- relay_uav_overlap_zero: PASS
- energy_component_overlap_zero: PASS
- charging_pass: PASS
- arrival_timing_pass: PASS
- reserve_pass: PASS
- full_trajectory_communication_feasible: FAIL
- exact_validation_pass: PASS
- service_option_space_complete: PASS
- status_mapping_pass: PASS

## 3. Candidate-space sensitivity

| spacing (m) | candidates | service options | solver | baseline | runtime (s) |
|---:|---:|---:|---|---|---:|
| 1500 | 135 | 990 | INFEASIBLE | INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET | 28.57 |
| 1000 | 270 | 2114 | INFEASIBLE | INFEASIBLE_PROVEN_ON_DISCRETE_CANDIDATE_SET | 68.25 |
| 750 | 449 | 3460 | UNKNOWN | UNRESOLVED | 178.21 |

## 4. Exact validation

- B-Small-1: PASS
- B-Small-2: PASS
- B-Small-3: PASS
- B-Small-4: PASS

## 5. Resource/communication audit

- all_demands_candidate_coverable: PASS
- all_demands_scheduled_covered: FAIL
- relay_uav_overlap_zero: PASS
- energy_component_overlap_zero: PASS
- charging_pass: PASS
- arrival_timing_pass: PASS
- reserve_pass: PASS
- full_trajectory_communication_feasible: FAIL
- exact_validation_pass: PASS
- service_option_space_complete: PASS
- status_mapping_pass: PASS
