# Q3-A 通信约束与中继联合建模基础审计

- status: **PASS**
- communication distance model: **3D Euclidean**
- candidate count before/after: 135 / 135
- coverage candidate count before/after: 121 / 121
- representative routes: 4; all Q2 baseline trips: 25
- max dt coverage difference: 0.00183229; max blind-duration difference: 2 s
- endpoint buffer sensitivity (0/15/30 m): PASS; flips=0

## Gate checks

- q2_common_reuse: PASS
- q2_files_unmodified: PASS
- relay_data_audit: PASS
- communication_parameter_audit: PASS
- trajectory_climb_cruise_descent: PASS
- handover_communication_checked: PASS
- dem_los: PASS
- three_dimensional_distance: PASS
- fspl_and_bidirectional_budget: PASS
- direct_relay_outage_logic: PASS
- mid_segment_outage_detected: PASS
- blind_interval_extraction: PASS
- relay_candidate_geometry: PASS
- relay_energy: PASS
- relay_reserve: PASS
- energy_component_charging: PASS
- dt_sensitivity_documented: PASS
- endpoint_buffer_sensitivity: PASS
- alltrip_q2baseline_audit: PASS

## Unit tests
[
  {
    "test": "short_unobstructed_los",
    "pass": true,
    "detail": {
      "blocked": false,
      "min_clearance_m": 100.0,
      "critical_location": {
        "lon": 0.00035714285714285714,
        "lat": 0.0,
        "terrain_m": 0.0,
        "line_altitude_m": 100.0,
        "distance_from_start_m": 39.75714285714286
      },
      "distance_m": 556.6,
      "n_terrain_samples": 57
    }
  },
  {
    "test": "terrain_obstruction_los",
    "pass": true,
    "detail": {
      "blocked": true,
      "min_clearance_m": -50.0,
      "critical_location": {
        "lon": 0.0045535714285714285,
        "lat": 0.0,
        "terrain_m": 150.0,
        "line_altitude_m": 100.0,
        "distance_from_start_m": 506.90357142857147
      },
      "distance_m": 1113.2,
      "n_terrain_samples": 113
    }
  },
  {
    "test": "bidirectional_budget",
    "pass": true,
    "detail": {
      "available": false,
      "path_loss_db": 94.9650888741926,
      "loss_limit_db": 70.0,
      "margin_db": -24.965088874192602,
      "blocked": false,
      "distance_m": 556.6,
      "horizontal_distance_m": 556.6,
      "distance_3d_m": 556.6,
      "forward_loss_limit_db": 120.0,
      "reverse_loss_limit_db": 70.0,
      "los": {
        "blocked": false,
        "min_clearance_m": 100.0,
        "critical_location": {
          "lon": 0.00035714285714285714,
          "lat": 0.0,
          "terrain_m": 0.0,
          "line_altitude_m": 100.0,
          "distance_from_start_m": 39.75714285714286
        },
        "distance_m": 556.6,
        "n_terrain_samples": 57
      }
    }
  },
  {
    "test": "direct_priority",
    "pass": true
  },
  {
    "test": "relay_success",
    "pass": true
  },
  {
    "test": "single_link_failure_is_outage",
    "pass": true
  },
  {
    "test": "mid_segment_outage",
    "pass": true,
    "detail": {
      "n_samples": 3,
      "direct_samples": 2,
      "relay_samples": 0,
      "outage_samples": 1,
      "outage_duration_s": 2.0,
      "direct_fail_intervals": [
        {
          "trip_id": "MID",
          "segment_first": "middle",
          "segment_last": "middle",
          "start_s": 2.0,
          "end_s": 2.0,
          "duration_s": 2.0,
          "n_samples": 1,
          "lon_min": 0.01,
          "lon_max": 0.01,
          "lat_min": 0.0,
          "lat_max": 0.0,
          "alt_min_m": 100.0,
          "alt_max_m": 100.0,
          "sample_times_s": [
            2.0
          ]
        }
      ],
      "min_link_margin_db": -6.008060479142898,
      "communication_feasible": false,
      "samples": [
        {
          "trip_id": "MID",
          "t_s": 0.0,
          "x_lon": 0.001,
          "y_lat": 0.0,
          "z_m": 200.0,
          "phase": "cruise",
          "segment": "start",
          "state": "DIRECT",
          "direct_available": true,
          "direct_margin_db": 8.433756814094735,
          "relay_margin_db": null,
          "selected_relay_id": null,
          "min_margin_db": 8.433756814094735
        },
        {
          "trip_id": "MID",
          "t_s": 2.0,
          "x_lon": 0.01,
          "y_lat": 0.0,
          "z_m": 100.0,
          "phase": "cruise",
          "segment": "middle",
          "state": "OUTAGE",
          "direct_available": false,
          "direct_margin_db": -6.008060479142898,
          "relay_margin_db": null,
          "selected_relay_id": null,
          "min_margin_db": -6.008060479142898
        },
        {
          "trip_id": "MID",
          "t_s": 4.0,
          "x_lon": 0.001,
          "y_lat": 0.0,
          "z_m": 200.0,
          "phase": "cruise",
          "segment": "end",
          "state": "DIRECT",
          "direct_available": true,
          "direct_margin_db": 8.433756814094735,
          "relay_margin_db": null,
          "selected_relay_id": null,
          "min_margin_db": 8.433756814094735
        }
      ]
    }
  },
  {
    "test": "relay_two_link_success",
    "pass": true,
    "detail": {
      "n_samples": 1,
      "direct_samples": 0,
      "relay_samples": 1,
      "outage_samples": 0,
      "outage_duration_s": 0.0,
      "direct_fail_intervals": [
        {
          "trip_id": "RELAY",
          "segment_first": "test",
          "segment_last": "test",
          "start_s": 1.0,
          "end_s": 1.0,
          "duration_s": 1.0,
          "n_samples": 1,
          "lon_min": 0.005,
          "lon_max": 0.005,
          "lat_min": 0.0,
          "lat_max": 0.0,
          "alt_min_m": 100.0,
          "alt_max_m": 100.0,
          "sample_times_s": [
            1.0
          ]
        }
      ],
      "min_link_margin_db": 21.055511039087023,
      "communication_feasible": true
    }
  },
  {
    "test": "relay_one_link_only_is_outage",
    "pass": true,
    "detail": {
      "n_samples": 1,
      "direct_samples": 0,
      "relay_samples": 0,
      "outage_samples": 1,
      "outage_duration_s": 1.0,
      "direct_fail_intervals": [
        {
          "trip_id": "RELAY",
          "segment_first": "test",
          "segment_last": "test",
          "start_s": 1.0,
          "end_s": 1.0,
          "duration_s": 1.0,
          "n_samples": 1,
          "lon_min": 0.005,
          "lon_max": 0.005,
          "lat_min": 0.0,
          "lat_max": 0.0,
          "alt_min_m": 100.0,
          "alt_max_m": 100.0,
          "sample_times_s": [
            1.0
          ]
        }
      ],
      "min_link_margin_db": -5.053892385818699,
      "communication_feasible": false
    }
  },
  {
    "test": "fspl_units",
    "pass": true
  },
  {
    "test": "distance_3d_vertical_200m",
    "pass": true
  },
  {
    "test": "distance_3d_3_4_5",
    "pass": true,
    "detail": {
      "horizontal_m": 300.0,
      "distance_3d_m": 500.0
    }
  },
  {
    "test": "fspl_uses_3d_distance",
    "pass": true,
    "detail": {
      "available": false,
      "path_loss_db": 94.03362492095249,
      "loss_limit_db": 70.0,
      "margin_db": -24.03362492095249,
      "blocked": false,
      "distance_m": 500.0,
      "horizontal_distance_m": 300.0,
      "distance_3d_m": 500.0,
      "forward_loss_limit_db": 120.0,
      "reverse_loss_limit_db": 70.0,
      "los": {
        "blocked": false,
        "min_clearance_m": 153.33333333333334,
        "critical_location": {
          "lon": 0.00035932446999640676,
          "lat": 0.0,
          "terrain_m": 0.0,
          "line_altitude_m": 153.33333333333334,
          "distance_from_start_m": 40.0
        },
        "distance_m": 300.0,
        "n_terrain_samples": 31
      }
    }
  }
]

## Blind interval validation
[
  {
    "trip_id": "Q2BASE-01",
    "dt_s": 5.0,
    "fail_sample_count": 0,
    "covered_fail_sample_count": 0,
    "false_included_pass_samples": 0,
    "interval_count": 0,
    "expected_interval_count": 0,
    "duration_from_intervals_s": 0.0,
    "duration_from_samples_s": 0.0,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 5.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-01",
    "dt_s": 2.0,
    "fail_sample_count": 0,
    "covered_fail_sample_count": 0,
    "false_included_pass_samples": 0,
    "interval_count": 0,
    "expected_interval_count": 0,
    "duration_from_intervals_s": 0.0,
    "duration_from_samples_s": 0.0,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 2.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-01",
    "dt_s": 1.0,
    "fail_sample_count": 0,
    "covered_fail_sample_count": 0,
    "false_included_pass_samples": 0,
    "interval_count": 0,
    "expected_interval_count": 0,
    "duration_from_intervals_s": 0.0,
    "duration_from_samples_s": 0.0,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 1.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-02",
    "dt_s": 5.0,
    "fail_sample_count": 207,
    "covered_fail_sample_count": 207,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1020.4076514058476,
    "duration_from_samples_s": 1020.4076514058476,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 5.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-02",
    "dt_s": 2.0,
    "fail_sample_count": 513,
    "covered_fail_sample_count": 513,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1018.4076514058476,
    "duration_from_samples_s": 1018.4076514058476,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 2.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-02",
    "dt_s": 1.0,
    "fail_sample_count": 1024,
    "covered_fail_sample_count": 1024,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1019.4076514058476,
    "duration_from_samples_s": 1019.4076514058476,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 1.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-03",
    "dt_s": 5.0,
    "fail_sample_count": 261,
    "covered_fail_sample_count": 261,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1284.270471840418,
    "duration_from_samples_s": 1284.270471840418,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 5.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-03",
    "dt_s": 2.0,
    "fail_sample_count": 644,
    "covered_fail_sample_count": 644,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1282.270471840418,
    "duration_from_samples_s": 1282.270471840418,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 2.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-03",
    "dt_s": 1.0,
    "fail_sample_count": 1287,
    "covered_fail_sample_count": 1287,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1283.270471840418,
    "duration_from_samples_s": 1283.270471840418,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 1.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-04",
    "dt_s": 5.0,
    "fail_sample_count": 245,
    "covered_fail_sample_count": 245,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1213.0822765884627,
    "duration_from_samples_s": 1213.0822765884627,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 5.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-04",
    "dt_s": 2.0,
    "fail_sample_count": 609,
    "covered_fail_sample_count": 609,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1211.0822765884627,
    "duration_from_samples_s": 1211.0822765884627,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 2.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  },
  {
    "trip_id": "Q2BASE-04",
    "dt_s": 1.0,
    "fail_sample_count": 1215,
    "covered_fail_sample_count": 1215,
    "false_included_pass_samples": 0,
    "interval_count": 1,
    "expected_interval_count": 1,
    "duration_from_intervals_s": 1211.0822765884627,
    "duration_from_samples_s": 1211.0822765884627,
    "duration_error_s": 0.0,
    "duration_tolerance_s": 1.0,
    "ordered": true,
    "sorted": true,
    "non_overlapping": true,
    "envelope_coverage": true,
    "pass": true
  }
]

## Relay energy/altitude tests
[
  {
    "test": "agl_60_m",
    "agl_m": 60.0,
    "feasible": true,
    "lon": 109.2308517,
    "lat": 23.0085095,
    "altitude_msl_m": 188.02713012695312,
    "service_start_s": 5000.0,
    "service_end_s": 5060.0,
    "relay_ready_s": 5000.0,
    "launch_start_s": 4774.918217468262,
    "return_end_s": 5080.109043375651,
    "resource_end_s": 5380.109043375651,
    "out_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 50.32713012695312,
      "h_dn": 0.0,
      "t": 15.08178253173828,
      "e_up": 0.005360084131264392,
      "e_cru": 0.0,
      "e": 0.005360084131264392,
      "extra_hover_vertical_m": 10.0
    },
    "back_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 0.0,
      "h_dn": 50.32713012695312,
      "t": 20.10904337565104,
      "e_up": 0.0,
      "e_cru": 0.0,
      "e": 0.0,
      "extra_hover_vertical_m": 10.0
    },
    "flight_energy_kwh": 0.005360084131264392,
    "service_energy_kwh": 0.018333333333333333,
    "total_energy_kwh": 0.023693417464597726,
    "reserve_limit_kwh": 2.5600000000000005,
    "energy_margin_kwh": 2.5363065825354028,
    "soc_after": 0.9925958070423132,
    "charge_time_s": 46.646415633426805,
    "max_service_s": 8360.639724661318,
    "reason": null,
    "soc_recomputed": 0.9925958070423132,
    "check_agl_legal": true,
    "check_msl_identity": true,
    "check_time_order": true,
    "check_reserve": true,
    "check_soc_after": true,
    "pass": true
  },
  {
    "test": "agl_150_m",
    "agl_m": 150.0,
    "feasible": true,
    "lon": 109.2308517,
    "lat": 23.0085095,
    "altitude_msl_m": 278.0271301269531,
    "service_start_s": 5000.0,
    "service_end_s": 5060.0,
    "relay_ready_s": 5000.0,
    "launch_start_s": 4752.418217468262,
    "return_end_s": 5110.109043375651,
    "resource_end_s": 5410.109043375651,
    "out_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 50.32713012695312,
      "h_dn": 0.0,
      "t": 37.581782531738284,
      "e_up": 0.01335661190904217,
      "e_cru": 0.0,
      "e": 0.01335661190904217,
      "extra_hover_vertical_m": 100.0
    },
    "back_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 0.0,
      "h_dn": 50.32713012695312,
      "t": 50.10904337565104,
      "e_up": 0.0,
      "e_cru": 0.0,
      "e": 0.0,
      "extra_hover_vertical_m": 100.0
    },
    "flight_energy_kwh": 0.01335661190904217,
    "service_energy_kwh": 0.018333333333333333,
    "total_energy_kwh": 0.031689945242375506,
    "reserve_limit_kwh": 2.5600000000000005,
    "energy_margin_kwh": 2.528310054757625,
    "soc_after": 0.9900968921117577,
    "charge_time_s": 62.389579695926706,
    "max_service_s": 8334.469270115862,
    "reason": null,
    "soc_recomputed": 0.9900968921117577,
    "check_agl_legal": true,
    "check_msl_identity": true,
    "check_time_order": true,
    "check_reserve": true,
    "check_soc_after": true,
    "pass": true
  },
  {
    "test": "agl_300_m",
    "agl_m": 300.0,
    "feasible": true,
    "lon": 109.2308517,
    "lat": 23.0085095,
    "altitude_msl_m": 428.0271301269531,
    "service_start_s": 5000.0,
    "service_end_s": 5060.0,
    "relay_ready_s": 5000.0,
    "launch_start_s": 4714.918217468262,
    "return_end_s": 5160.109043375651,
    "resource_end_s": 5460.109043375651,
    "out_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 50.32713012695312,
      "h_dn": 0.0,
      "t": 75.08178253173828,
      "e_up": 0.026684158205338468,
      "e_cru": 0.0,
      "e": 0.026684158205338468,
      "extra_hover_vertical_m": 250.0
    },
    "back_leg": {
      "d": 0.0,
      "zmax": 128.02713012695312,
      "z_cruise": 178.02713012695312,
      "h_up": 0.0,
      "h_dn": 50.32713012695312,
      "t": 100.10904337565104,
      "e_up": 0.0,
      "e_cru": 0.0,
      "e": 0.0,
      "extra_hover_vertical_m": 250.0
    },
    "flight_energy_kwh": 0.026684158205338468,
    "service_energy_kwh": 0.018333333333333333,
    "total_energy_kwh": 0.0450174915386718,
    "reserve_limit_kwh": 2.5600000000000005,
    "energy_margin_kwh": 2.514982508461329,
    "soc_after": 0.9859320338941651,
    "charge_time_s": 88.62818646676011,
    "max_service_s": 8290.85184587344,
    "reason": null,
    "soc_recomputed": 0.9859320338941651,
    "check_agl_legal": true,
    "check_msl_identity": true,
    "check_time_order": true,
    "check_reserve": true,
    "check_soc_after": true,
    "pass": true
  },
  {
    "test": "short_service_feasible",
    "feasible": true,
    "energy_margin_kwh": 2.5363065825354028,
    "pass": true
  },
  {
    "test": "long_service_reserve_infeasible",
    "feasible": false,
    "reason": "reserve_violation",
    "energy_margin_kwh": -26.473137861909045,
    "pass": true
  },
  {
    "test": "hover_below_cruise_no_extra_vertical",
    "extra_hover_vertical_m": 0.0,
    "pass": true
  },
  {
    "test": "hover_above_cruise_extra_vertical",
    "extra_hover_vertical_m": 250.0,
    "flight_time_delta_s": 45.833333333333336,
    "flight_energy_delta_kwh": 0.02221257716049383,
    "pass": true
  }
]

## Charging audit
{
  "soc_0_0_s": 1800.0,
  "soc_0_45_s": 1215.0,
  "soc_0_89_s": 643.0,
  "soc_0_9_s": 629.9999999999998,
  "soc_0_95_s": 315.0000000000003,
  "soc_1_0_s": 0.0,
  "monotone_non_increasing": true,
  "soc_1_s": 0.0,
  "continuity_0_90": true,
  "pass": true
}

## Scope
- Q1 modified: NO
- Q2 numerical code/results modified: NO
- Q3-B/joint ALNS entered: NO
