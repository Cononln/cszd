# Q2 C–E Final Report

- status: **PASS**
- formal solution: `seed-20260925`
- metrics: {"WTD": 491437.69967409596, "Cmax_s": 12813.427822427877, "total_energy_kwh": 107.60322797016207, "n_trips": 41.0, "total_operation_time_s": 69867.17788120094}

## Gate C
- solver: FEASIBLE
- checks: {"uav_type": true, "uav_overlap": true, "battery_overlap": true, "battery_type": true, "soc": true, "charge_before_reuse": true}

## Gate D
- seeds requested/completed/failed: 5/5/0
- operators: random/related/worst destroy; cheapest/deadline-first repair; reverse-stop local search
- acceptance: simulated annealing; archive: fixed-reference Pareto

## Gate E
- validator: **PASS**
- checks: {"all_boxes_delivered_once": true, "missing_boxes": true, "duplicate_boxes": true, "no_split_boxes": true, "unknown_boxes": true, "mass_pass": true, "volume_pass": true, "energy_pass": true, "return_reserve_pass": true, "route_energy_recomputed": true, "delivery_recomputed": true, "first_deadlines_pass": true, "medical_deadlines_pass": true, "uav_type_pass": true, "uav_overlap_zero": true, "battery_type_pass": true, "battery_count_pass": true, "battery_overlap_zero": true, "soc_pass": true, "charge_pass": true, "charge_before_reuse_pass": true, "solver_validator_consistent": true}

## Exact validation
[
  {
    "instance": "fixed_singleton_3",
    "n_boxes": 3,
    "exact_status": "OPTIMAL",
    "exact_objective_Cmax_s": 2365.744762011775,
    "alns_objective_Cmax_s": 2365.744762011775,
    "gap": 0.0,
    "validator_status": "PASS"
  },
  {
    "instance": "fixed_singleton_5",
    "n_boxes": 5,
    "exact_status": "OPTIMAL",
    "exact_objective_Cmax_s": 3727.244762011775,
    "alns_objective_Cmax_s": 3727.244762011775,
    "gap": 0.0,
    "validator_status": "PASS"
  },
  {
    "instance": "fixed_singleton_10",
    "n_boxes": 10,
    "exact_status": "OPTIMAL",
    "exact_objective_Cmax_s": 6282.844762011775,
    "alns_objective_Cmax_s": 6282.844762011775,
    "gap": 0.0,
    "validator_status": "PASS"
  }
]

Q1 source files were not modified by this Q2 run.
