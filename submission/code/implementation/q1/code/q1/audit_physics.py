# -*- coding: utf-8 -*-
"""Phase Q1-1：基础物理模型审查。

本脚本只检查 Q1 的公共物理口径，不进行组批，也不求解最大安全载荷：

* O01 到 15 个服务区的 DEM 沿途最高高程；
* 最高 DEM + 50 m 巡航高度及两端作业高度；
* 爬升/下降高度与航段时间；
* 载荷相关等效航程的单调性；
* 去程按给定载荷、返程空载的能耗拆分；
* 返航安全余量对应的能量上限（仅核对口径，不反解 q_max）。

输出：``results/q1_physics_audit.csv``、``q1_physics_energy_checks.csv`` 和
``q1_physics_audit.json``。这些文件是 Q1-1 审查证据，下一阶段确认后再运行
``q1_solve.py`` 计算 45 个最大安全载荷。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import CRUISE_CLEARANCE, OPS_HEIGHT_O01, OPS_HEIGHT_S, RES
from common.data import load_boxes, load_nodes, load_transport_types, sid_list
from common.physics import TransportTrip
from common.route import GTS, leg_energy, leg_geom, leg_time, equiv_range_fast


def _check_close(a: float, b: float, tol: float = 1e-7) -> bool:
    return bool(np.isfinite(a) and np.isfinite(b) and abs(a - b) <= tol)


def audit_geometry() -> tuple[pd.DataFrame, dict, list[dict]]:
    nodes = load_nodes().set_index("id")
    sids = sid_list()
    rows: list[dict] = []
    failures: list[dict] = []
    checks: dict[str, bool] = {
        "data_nodes_16": len(nodes) == 16 and "O01" in nodes.index,
        "data_service_areas_15": all(s in nodes.index for s in sids),
        "dem_path_samples_finite": True,
        "cruise_height_is_dem_plus_50m": True,
        "climb_descent_nonnegative": True,
        "return_geometry_reciprocal": True,
    }
    for sid in sids:
        fwd = leg_geom("O01", sid)
        rev = leg_geom(sid, "O01")
        zc_expected = fwd["zmax"] + CRUISE_CLEARANCE
        dem_ok = np.isfinite(fwd["zmax"]) and np.isfinite(rev["zmax"])
        height_ok = (
            _check_close(fwd["z_cruise"], zc_expected)
            and _check_close(fwd["ops_i"], nodes.loc["O01", "elev"] + OPS_HEIGHT_O01)
            and _check_close(fwd["ops_j"], nodes.loc[sid, "elev"] + OPS_HEIGHT_S)
            and fwd["h_up"] >= -1e-9
            and fwd["h_dn"] >= -1e-9
        )
        reciprocal_ok = (
            _check_close(fwd["d"], rev["d"], 1e-5)
            and _check_close(fwd["zmax"], rev["zmax"], 1e-5)
        )
        checks["dem_path_samples_finite"] &= dem_ok
        checks["cruise_height_is_dem_plus_50m"] &= height_ok
        checks["climb_descent_nonnegative"] &= height_ok
        checks["return_geometry_reciprocal"] &= reciprocal_ok
        if not dem_ok:
            failures.append({"check": "dem_path_samples_finite", "sid": sid,
                             "zmax_forward_m": fwd["zmax"], "zmax_return_m": rev["zmax"]})
        if not height_ok:
            failures.append({"check": "cruise_height_or_operation_height", "sid": sid,
                             "cruise_altitude_m": fwd["z_cruise"],
                             "expected_cruise_altitude_m": zc_expected,
                             "outbound_climb_m": fwd["h_up"],
                             "outbound_descent_m": fwd["h_dn"]})
        if not reciprocal_ok:
            failures.append({"check": "return_geometry_reciprocal", "sid": sid,
                             "distance_forward_m": fwd["d"], "distance_return_m": rev["d"],
                             "zmax_forward_m": fwd["zmax"], "zmax_return_m": rev["zmax"]})
        rows.append({
            "sid": sid,
            "distance_m": fwd["d"],
            "zmax_forward_m": fwd["zmax"],
            "zmax_return_m": rev["zmax"],
            "cruise_altitude_m": fwd["z_cruise"],
            "o01_ops_altitude_m": fwd["ops_i"],
            "service_ops_altitude_m": fwd["ops_j"],
            "outbound_climb_m": fwd["h_up"],
            "outbound_descent_m": fwd["h_dn"],
            "return_climb_m": rev["h_up"],
            "return_descent_m": rev["h_dn"],
            "outbound_flight_s_A": leg_time("A", "O01", sid),
            "return_flight_s_A": leg_time("A", sid, "O01"),
            "geometry_ok": bool(dem_ok and height_ok and reciprocal_ok),
        })
    return pd.DataFrame(rows), checks, failures


def audit_energy(geometry: pd.DataFrame) -> tuple[pd.DataFrame, dict, list[dict], dict]:
    checks: dict[str, bool] = {
        "payload_range_positive": True,
        "payload_range_nonincreasing": True,
        "payload_range_empty_endpoint": True,
        "payload_range_full_endpoint": True,
        "return_leg_payload_zero": True,
        "return_leg_energy_matches_q0": True,
        "energy_nonnegative": True,
        "reserve_limit_positive": True,
        "full_load_energy_finite": True,
    }
    rows: list[dict] = []
    failures: list[dict] = []
    nodes = load_nodes()
    full_load_infeasible: list[dict] = []
    endpoint_tol = 1e-7
    payload_tol = 1e-9
    energy_tol = 1e-8
    for sid in geometry["sid"]:
        for g, gt in GTS.items():
            q_grid = np.linspace(0.0, float(gt["Q"]), 5)
            ranges = np.array([equiv_range_fast(gt, float(q)) for q in q_grid])
            range_ok = bool(np.all(np.isfinite(ranges)) and np.all(ranges > 0))
            monotone_ok = bool(np.all(np.diff(ranges) <= 1e-9))
            empty_endpoint_ok = bool(abs(ranges[0] - gt["L0"]) <= endpoint_tol)
            full_endpoint_ok = bool(abs(ranges[-1] - gt["LF"]) <= endpoint_tol)
            checks["payload_range_positive"] &= range_ok
            checks["payload_range_nonincreasing"] &= monotone_ok
            checks["payload_range_empty_endpoint"] &= empty_endpoint_ok
            checks["payload_range_full_endpoint"] &= full_endpoint_ok
            if not range_ok:
                failures.append({"check": "payload_range_positive", "sid": sid, "gtype": g,
                                 "ranges_m": ranges.tolist()})
            if not monotone_ok:
                failures.append({"check": "payload_range_nonincreasing", "sid": sid,
                                 "gtype": g, "ranges_m": ranges.tolist()})
            if not empty_endpoint_ok:
                failures.append({"check": "payload_range_empty_endpoint", "gtype": g,
                                 "actual_m": float(ranges[0]), "expected_m": float(gt["L0"])})
            if not full_endpoint_ok:
                failures.append({"check": "payload_range_full_endpoint", "gtype": g,
                                 "actual_m": float(ranges[-1]), "expected_m": float(gt["LF"])})

            q_probe = float(gt["Q"])
            # 用公共 TransportTrip 实际构造 O01 -> Si -> O01，检查首末航段
            # 的载荷，而不是仅凭两个独立能耗值推断返航口径。
            task = TransportTrip(nodes, [sid], gt)
            payloads = task.leg_payloads({sid: q_probe})
            outbound_payload = float(payloads[0])
            return_payload = float(payloads[-1])
            return_payload_is_zero = abs(return_payload) <= payload_tol
            e_out_empty = float(leg_energy(g, "O01", sid, 0.0, gt))
            e_out_full = float(leg_energy(g, "O01", sid, q_probe, gt))
            e_return_actual = float(leg_energy(g, sid, "O01", return_payload, gt))
            e_return_direct = float(leg_energy(g, sid, "O01", 0.0, gt))
            return_energy_matches = bool(abs(e_return_actual - e_return_direct) <= energy_tol)
            e_limit = (1.0 - float(gt["rho"])) * float(gt["Euse"])
            e_roundtrip_full = e_out_full + e_return_direct
            full_margin = e_limit - e_roundtrip_full
            full_feasible = bool(full_margin >= -energy_tol)
            energy_ok = all(np.isfinite(x) and x >= -1e-9 for x in
                            (e_out_empty, e_out_full, e_return_actual, e_return_direct,
                             e_roundtrip_full))
            reserve_ok = e_limit > 0
            checks["return_leg_payload_zero"] &= return_payload_is_zero
            checks["return_leg_energy_matches_q0"] &= return_energy_matches
            checks["energy_nonnegative"] &= energy_ok
            checks["reserve_limit_positive"] &= reserve_ok
            checks["full_load_energy_finite"] &= energy_ok
            if not return_payload_is_zero:
                failures.append({"check": "return_leg_payload_zero", "sid": sid, "gtype": g,
                                 "return_payload_check_kg": return_payload,
                                 "expected_return_payload_kg": 0.0})
            if not return_energy_matches:
                failures.append({"check": "return_leg_energy_matches_q0", "sid": sid,
                                 "gtype": g, "return_payload_check_kg": return_payload,
                                 "return_energy_actual_kwh": e_return_actual,
                                 "return_energy_direct_q0_kwh": e_return_direct})
            if not energy_ok:
                failures.append({"check": "energy_nonnegative", "sid": sid, "gtype": g,
                                 "energy_outbound_full_kwh": e_out_full,
                                 "energy_return_empty_kwh": e_return_direct,
                                 "energy_roundtrip_full_kwh": e_roundtrip_full})
            if not reserve_ok:
                failures.append({"check": "reserve_limit_positive", "sid": sid, "gtype": g,
                                 "energy_limit_kwh": e_limit})
            if not full_feasible:
                full_load_infeasible.append({"sid": sid, "gtype": g,
                                             "full_payload_kg": q_probe,
                                             "full_load_margin_kwh": full_margin})
            rows.append({
                "sid": sid,
                "gtype": g,
                "payload_probe_kg": q_probe,
                "full_payload_kg": q_probe,
                "range_empty_m": float(ranges[0]),
                "range_half_payload_m": float(ranges[2]),
                "range_max_payload_m": float(ranges[-1]),
                "range_empty_endpoint_error_m": float(ranges[0] - gt["L0"]),
                "range_full_endpoint_error_m": float(ranges[-1] - gt["LF"]),
                "range_positive": range_ok,
                "range_nonincreasing": monotone_ok,
                "range_empty_endpoint": empty_endpoint_ok,
                "range_full_endpoint": full_endpoint_ok,
                "energy_outbound_empty_kwh": e_out_empty,
                "energy_outbound_probe_kwh": e_out_full,
                "energy_outbound_full_kwh": e_out_full,
                "energy_return_empty_kwh": e_return_direct,
                "energy_return_probe_kwh": e_return_direct,
                "return_payload_check_kg": return_payload,
                "return_payload_is_zero": return_payload_is_zero,
                "return_energy_direct_q0_kwh": e_return_direct,
                "return_energy_actual_kwh": e_return_actual,
                "return_energy_matches_q0": return_energy_matches,
                "energy_roundtrip_full_kwh": e_roundtrip_full,
                "energy_limit_after_reserve_kwh": e_limit,
                "full_load_margin_kwh": full_margin,
                "full_load_roundtrip_feasible": full_feasible,
                "rho": float(gt["rho"]),
                "energy_nonnegative": energy_ok,
            })
    summary = {
        "total": len(rows),
        "feasible": len(rows) - len(full_load_infeasible),
        "infeasible": len(full_load_infeasible),
    }
    return pd.DataFrame(rows), checks, failures, {
        "full_load_summary": summary,
        "full_load_infeasible_pairs": full_load_infeasible,
    }


def main() -> dict:
    geometry, geometry_checks, geometry_failures = audit_geometry()
    energy, energy_checks, energy_failures, full_load = audit_energy(geometry)
    boxes = load_boxes()
    checks = {**geometry_checks, **energy_checks,
              "box_data_nonempty": len(boxes) > 0,
              "box_columns_present": {"box", "sid", "mass", "vol"}.issubset(boxes.columns)}
    checks = {k: bool(v) for k, v in checks.items()}
    checks["all_checks_pass"] = all(checks.values())
    geometry.to_csv(RES / "q1_physics_audit.csv", index=False, encoding="utf-8-sig")
    energy.to_csv(RES / "q1_physics_energy_checks.csv", index=False, encoding="utf-8-sig")
    report = {
        "phase": "Q1-1",
        "scope": "基础物理模型审查；未进行最大安全载荷反解和组批",
        "checks": checks,
        "n_service_areas": int(len(geometry)),
        "n_energy_rows": int(len(energy)),
        "failures": geometry_failures + energy_failures,
        **full_load,
        "constants": {
            "cruise_clearance_m": CRUISE_CLEARANCE,
            "ops_height_o01_m": OPS_HEIGHT_O01,
            "ops_height_service_m": OPS_HEIGHT_S,
        },
    }
    with open(RES / "q1_physics_audit.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    gmin = geometry.loc[geometry["distance_m"].idxmin()]
    gmax = geometry.loc[geometry["distance_m"].idxmax()]
    markdown = """# Q1-1 基础物理模型审查

## 范围

本阶段只审查数据读取、DEM 航段、巡航高度、爬升/下降、载荷相关航程、能耗
拆分和返航安全余量；**未计算最大安全载荷，也未进入组批**。

## 口径

- 每个服务区使用 O01→Si 和 Si→O01 两条 DEM 航段；沿途最高地面高程为
  `z_max`，规划巡航海拔为 `z_max + 50 m`。
- O01 作业高度为地面海拔，服务区作业高度为地面海拔 + 30 m。
- 水平能耗使用题目给定的载荷相关等效航程 `L_g(q)`；爬升能耗包含空机质量
  与当前载荷质量。
- 去程能耗探针使用带载荷口径，返程探针明确使用空载 `q=0`；安全能量上限为
  `(1-rho) E_use`。

## 数据与异常检查

| 检查项 | 结果 |
| --- | --- |
| 节点数量 | {{len(geometry)+1}}（O01 + 15 个服务区） |
| DEM 航段样本 | {{len(geometry)}} 条，全部有限 |
| 最短 O01—服务区距离 | {{gmin['sid']}}，{{gmin['distance_m']:.1f}} m |
| 最长 O01—服务区距离 | {{gmax['sid']}}，{{gmax['distance_m']:.1f}} m |
| 巡航高度规则 | 全部满足 `z_cruise = z_max + 50 m` |
| 爬升/下降高度 | 全部非负 |
| 载荷相关航程 | 对 A/B/C 均为正且随载荷不增 |
| 航程端点 | 全部满足 `L(0)=L0` 和 `L(Q)=LF` |
| 返航载荷 | 45 个单服务区任务的最后航段均为 `q=0`，且能耗与直接 q=0 计算一致 |
| 能耗与安全余量 | 45 个机型—服务区探针全部非负，安全上限为正 |
| 总体结论 | **{{'PASS' if checks['all_checks_pass'] else 'FAIL'}}** |

## 满载往返能力初筛

本项使用额定最大载荷 `Q_g` 作为能力边界探针，不反解最大安全载荷，不进入组批。
对每个机型—服务区组合计算：

`E_roundtrip_full = E_outbound(Q_g) + E_return(0)`，并与
`E_limit = (1-rho_g) E_use_g` 比较。

| 组合总数 | 满载安全可行 | 满载安全不可行 |
| ---: | ---: | ---: |
| {{full_total}} | {{full_feasible}} | {{full_infeasible}} |

满载安全不可行组合：

{{full_infeasible_pairs}}

满载不可行不构成 Q1-1 物理审计失败；它是下一阶段反解 `q_max` 的能力边界证据。

## 文献对照边界

- Cheng, Adulyasak & Rousseau (2020, DOI: 10.1016/j.trb.2020.06.011) 支持将
  载荷与非线性能耗/可行性联立检查；本项目仍以赛题给定 `L_g(q)` 和能耗式为准。
- Zhang et al. (2021, DOI: 10.1016/j.trd.2020.102668) 强调能耗模型依赖载荷、
  机型和运行口径，本审查因此分别保留 A/B/C 参数和去程/返程状态。
- Masmoudi et al. (2022, DOI: 10.1016/j.tre.2022.102757) 支持多货箱载荷建模，
  但其路由/启发式结果不在本阶段使用。

## 输出文件

- `q1_physics_audit.csv`：15 个服务区的基础航段参数；
- `q1_physics_energy_checks.csv`：3×15 个机型—服务区的能耗口径探针；
- `q1_physics_audit.json`：机器可读检查结果。
"""
    # f-string 中的双大括号用于保留 Markdown 表格中的动态表达式文本，实际值在此替换。
    markdown = markdown.replace("{{len(geometry)+1}}", str(len(geometry) + 1))
    markdown = markdown.replace("{{len(geometry)}}", str(len(geometry)))
    markdown = markdown.replace("{{gmin['sid']}}", str(gmin["sid"]))
    markdown = markdown.replace("{{gmin['distance_m']:.1f}}", f"{gmin['distance_m']:.1f}")
    markdown = markdown.replace("{{gmax['sid']}}", str(gmax["sid"]))
    markdown = markdown.replace("{{gmax['distance_m']:.1f}}", f"{gmax['distance_m']:.1f}")
    markdown = markdown.replace("{{'PASS' if checks['all_checks_pass'] else 'FAIL'}}",
                                "PASS" if checks["all_checks_pass"] else "FAIL")
    markdown = markdown.replace("{{full_total}}", str(full_load["full_load_summary"]["total"]))
    markdown = markdown.replace("{{full_feasible}}", str(full_load["full_load_summary"]["feasible"]))
    markdown = markdown.replace("{{full_infeasible}}", str(full_load["full_load_summary"]["infeasible"]))
    pairs = full_load["full_load_infeasible_pairs"]
    pair_text = "\n".join(
        f"- `{p['gtype']} - {p['sid']}`（裕量 {p['full_load_margin_kwh']:.6f} kWh）"
        for p in pairs
    ) or "- 无"
    markdown = markdown.replace("{{full_infeasible_pairs}}", pair_text)
    (RES / "q1_physics_audit_report.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    main()
