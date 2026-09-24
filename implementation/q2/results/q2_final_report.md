# Q2 Final Methodology Revision and Freeze Audit

- status: **PASS**
- formal solution: `seed-20260925-best`
- metrics: {"WTD": 14791.774700396316, "Cmax_s": 11992.999291929716, "total_energy_kwh": 79.33154169469012, "n_trips": 29.0, "total_operation_time_s": 51509.78800583729}

## Methodology repairs
- exact: real structural enumeration; only completed instances are OPTIMAL.
- Pareto: seed archives globally de-duplicated and non-dominated filtered.
- repair: delta energy/time/trip/risk and all stop positions are evaluated.
- schedule: WTD then Cmax lexicographic CP-SAT stages.
- normalization: fixed anchor-derived ideal/nadir and ideal-distance selection.

## Gate E
{"all_boxes_delivered_once": true, "missing_boxes": true, "duplicate_boxes": true, "no_split_boxes": true, "unknown_boxes": true, "mass_pass": true, "volume_pass": true, "energy_pass": true, "return_reserve_pass": true, "route_energy_recomputed": true, "delivery_recomputed": true, "first_deadlines_pass": true, "medical_deadlines_pass": true, "uav_type_pass": true, "uav_overlap_zero": true, "battery_type_pass": true, "battery_count_pass": true, "battery_overlap_zero": true, "soc_pass": true, "charge_pass": true, "charge_before_reuse_pass": true, "solver_validator_consistent": true}

## Exact validation
[
  {
    "instance": "Small-1",
    "n_service_areas": 3,
    "n_boxes": 5,
    "exact_status": "OPTIMAL",
    "exact_objective": 0.129623345413112,
    "alns_objective": 0.1953479503666364,
    "absolute_gap": 0.06572460495352442,
    "relative_gap": 0.507042961621295,
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
        "Cmax_s": 3926.149615416045,
        "total_energy_kwh": 7.44638960495836,
        "n_trips": 5.0
      },
      "rho": 0.005
    },
    "exact_WTD": 0.0,
    "exact_Cmax_s": 1873.4697880341996,
    "exact_energy_kwh": 3.8147557183576732,
    "exact_n_trips": 2,
    "alns_WTD": 0.0,
    "alns_Cmax_s": 2804.80815020461,
    "alns_energy_kwh": 5.763133928749468,
    "alns_n_trips": 1,
    "validator_status": "PASS",
    "evaluated_structures": 3773
  },
  {
    "instance": "Small-2",
    "n_service_areas": 4,
    "n_boxes": 4,
    "exact_status": "OPTIMAL",
    "exact_objective": 0.18478554261664518,
    "alns_objective": 0.2518458473948996,
    "absolute_gap": 0.06706030477825445,
    "relative_gap": 0.3629088284107664,
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
        "Cmax_s": 2884.5570700296776,
        "total_energy_kwh": 6.271097617350606,
        "n_trips": 4.0
      },
      "rho": 0.005
    },
    "exact_WTD": 0.0,
    "exact_Cmax_s": 2106.375287086362,
    "exact_energy_kwh": 4.514585682134122,
    "exact_n_trips": 2,
    "alns_WTD": 0.0,
    "alns_Cmax_s": 2884.5570700296776,
    "alns_energy_kwh": 2.9892937427675874,
    "alns_n_trips": 1,
    "validator_status": "PASS",
    "evaluated_structures": 646
  },
  {
    "instance": "Small-3",
    "n_service_areas": 5,
    "n_boxes": 8,
    "exact_status": "FEASIBLE",
    "exact_objective": 0.24614830922424802,
    "alns_objective": 0.1797680273860844,
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
    "alns_Cmax_s": 2974.6240711505484,
    "alns_energy_kwh": 8.60819126218902,
    "alns_n_trips": 2,
    "validator_status": "PASS",
    "evaluated_structures": 331
  }
]

Q1 source files were not modified by this Q2 revision.
