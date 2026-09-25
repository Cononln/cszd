# Q2 Final Methodology Revision and Freeze Audit

- status: **PASS**
- formal solution: `seed-20260930-iter-0`
- metrics: {"WTD": 6228.862797380436, "Cmax_s": 9612.3086367231, "total_energy_kwh": 70.1181675670078, "n_trips": 25.0, "total_operation_time_s": 45796.642832170495}

## Methodology repairs
- exact: real structural enumeration; only completed instances are OPTIMAL.
- Pareto: seed archives globally de-duplicated and non-dominated filtered.
- repair: delta energy/time/trip/risk and all stop positions are evaluated.
- schedule: WTD then Cmax lexicographic CP-SAT stages.
- normalization: fixed anchor-derived bounds are used during search; final representative selection recomputes ideal/nadir from the global Pareto set.

## Gate E
{"all_boxes_delivered_once": true, "missing_boxes": true, "duplicate_boxes": true, "no_split_boxes": true, "unknown_boxes": true, "mass_pass": true, "volume_pass": true, "energy_pass": true, "return_reserve_pass": true, "route_energy_recomputed": true, "delivery_recomputed": true, "first_deadlines_pass": true, "medical_deadlines_pass": true, "uav_type_pass": true, "uav_overlap_zero": true, "battery_type_pass": true, "battery_count_pass": true, "battery_overlap_zero": true, "soc_pass": true, "charge_pass": true, "charge_before_reuse_pass": true, "solver_validator_consistent": true}

## Exact validation
[
  {
    "instance": "Small-1",
    "n_service_areas": 3,
    "n_boxes": 3,
    "exact_status": "OPTIMAL",
    "exact_objective": 0.2118533977969583,
    "alns_objective": 0.2118533977969583,
    "absolute_gap": 0.0,
    "relative_gap": 0.0,
    "comparison_status": "PASS",
    "benchmark_normalization": {
      "ideal": {
        "WTD": 0.0,
        "Cmax_s": 0.0,
        "total_energy_kwh": 0.0,
        "n_trips": 1.0
      },
      "nadir": {
        "WTD": 1.0,
        "Cmax_s": 2495.5496154160455,
        "total_energy_kwh": 4.039889118363298,
        "n_trips": 3.0
      },
      "rho": 0.005
    },
    "exact_WTD": 0.0,
    "exact_Cmax_s": 2088.2464662596676,
    "exact_energy_kwh": 3.1846057879736778,
    "exact_n_trips": 2,
    "alns_WTD": 0.0,
    "alns_Cmax_s": 2088.2464662596676,
    "alns_energy_kwh": 3.1846057879736778,
    "alns_n_trips": 2,
    "alns_status": "PASS",
    "alns_weight_profile": "balanced",
    "alns_runtime_s": 0.6870765000057872,
    "validator_status": "PASS",
    "evaluated_structures": 93
  },
  {
    "instance": "Small-2",
    "n_service_areas": 3,
    "n_boxes": 4,
    "exact_status": "OPTIMAL",
    "exact_objective": 0.1653796019425106,
    "alns_objective": 0.1894080559927922,
    "absolute_gap": 0.02402845405028159,
    "relative_gap": 0.145292731195679,
    "comparison_status": "PASS",
    "benchmark_normalization": {
      "ideal": {
        "WTD": 0.0,
        "Cmax_s": 0.0,
        "total_energy_kwh": 0.0,
        "n_trips": 1.0
      },
      "nadir": {
        "WTD": 1.0,
        "Cmax_s": 2866.9725500934887,
        "total_energy_kwh": 5.861111083043017,
        "n_trips": 4.0
      },
      "rho": 0.005
    },
    "exact_WTD": 0.0,
    "exact_Cmax_s": 1873.4697880341996,
    "exact_energy_kwh": 3.6551816496976164,
    "exact_n_trips": 2,
    "alns_WTD": 0.0,
    "alns_Cmax_s": 2148.2464662596676,
    "alns_energy_kwh": 3.4119487783821363,
    "alns_n_trips": 2,
    "alns_status": "PASS",
    "alns_weight_profile": "balanced",
    "alns_runtime_s": 0.6807051000068896,
    "validator_status": "PASS",
    "evaluated_structures": 573
  },
  {
    "instance": "Small-3",
    "n_service_areas": 5,
    "n_boxes": 8,
    "exact_status": "FEASIBLE",
    "exact_objective": 0.24614830922424802,
    "alns_objective": 0.1459461162519049,
    "absolute_gap": NaN,
    "relative_gap": NaN,
    "comparison_status": "UNRESOLVED",
    "benchmark_normalization": {
      "ideal": {
        "WTD": 0.0,
        "Cmax_s": 0.0,
        "total_energy_kwh": 0.0,
        "n_trips": 1.0
      },
      "nadir": {
        "WTD": 1.0,
        "Cmax_s": 5693.372550093489,
        "total_energy_kwh": 12.087023413644086,
        "n_trips": 8.0
      },
      "rho": 0.005
    },
    "exact_WTD": 0.0,
    "exact_Cmax_s": 2517.290518061747,
    "exact_energy_kwh": 11.77205228066623,
    "exact_n_trips": 6,
    "alns_WTD": 0.0,
    "alns_Cmax_s": 3213.2496154160453,
    "alns_energy_kwh": 6.969990740763403,
    "alns_n_trips": 3,
    "alns_status": "PASS",
    "alns_weight_profile": "balanced",
    "alns_runtime_s": 0.8435406000062358,
    "validator_status": "PASS",
    "evaluated_structures": 451
  }
]

Q1 source files were not modified by this Q2 revision.
