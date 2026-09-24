# -*- coding: utf-8 -*-
"""Phase Q1-2：单服务区连续最大安全载荷求解。

本脚本只处理单服务区任务 ``O01 -> Si -> O01`` 的连续质量边界：

    q_max(g, s) = max {q in [0, Q_g] : E_trip(g, s, q) <= E_limit(g)}

能耗公式和 DEM 航段全部复用冻结的 ``common.route.leg_energy``，不在这里
复制或改写物理模型。返程严格按空载 ``q=0`` 计算。Q1-3 的货箱离散组合、
体积约束和组批不属于本脚本职责。

文献边界：Cheng et al. (2020) 支持把非线性能耗直接放入可行性约束；
Zhang et al. (2021) 支持保留机型/载荷差异；Masmoudi et al. (2022) 支持
把连续载荷能力边界与后续多货箱离散优化分层。三篇论文均不替换赛题参数
或能耗公式。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import RES
from common.data import load_transport_types, sid_list
from common.route import GTS, leg_energy


ENERGY_TOL = 1e-8
PAYLOAD_TOL = 1e-6
BOUNDARY_TOL = 1e-7
GRID_POINTS = 101
MAX_ITER = 80
DELTA_KG = 1e-3


def roundtrip_energy(gtype: str, sid: str, q: float, gt: dict[str, float]) -> float:
    """Return ``E_outbound(q) + E_return(0)`` in kWh.

    The return payload is deliberately a literal zero.  Keeping this expression
    in one place makes the Q1-2 definition auditable and prevents accidental
    reuse of the outbound payload on the return leg.
    """
    return float(
        leg_energy(gtype, "O01", sid, float(q), gt)
        + leg_energy(gtype, sid, "O01", 0.0, gt)
    )


def _finite_grid(values: np.ndarray) -> bool:
    return bool(values.size and np.all(np.isfinite(values)))


def _monotone_non_decreasing(values: np.ndarray, tol: float = ENERGY_TOL) -> bool:
    return bool(_finite_grid(values) and np.all(np.diff(values) >= -tol))


def _nan(value: float | int | None = None) -> float:
    """Return a JSON/CSV friendly NaN value for unavailable diagnostics."""
    return float("nan")


def solve_single_service_qmax(
    gtype: str,
    sid: str,
    gt: dict[str, float],
    *,
    energy_tol: float = ENERGY_TOL,
    payload_tol: float = PAYLOAD_TOL,
    max_iter: int = MAX_ITER,
    grid_points: int = GRID_POINTS,
    delta: float = DELTA_KG,
) -> dict[str, Any]:
    """Solve and numerically validate one machine/service-area pair."""
    rated_q = float(gt["Q"])
    energy_limit = float((1.0 - gt["rho"]) * gt["Euse"])
    q_grid = np.linspace(0.0, rated_q, grid_points)
    energy_grid = np.array(
        [roundtrip_energy(gtype, sid, float(q), gt) for q in q_grid], dtype=float
    )
    energy_grid_finite = _finite_grid(energy_grid)
    energy_nondecreasing = _monotone_non_decreasing(energy_grid, energy_tol)

    e_empty = float(energy_grid[0]) if energy_grid_finite else _nan()
    e_full = float(energy_grid[-1]) if energy_grid_finite else _nan()
    empty_feasible = bool(energy_grid_finite and e_empty <= energy_limit + energy_tol)
    full_feasible = bool(energy_grid_finite and e_full <= energy_limit + energy_tol)

    q_max = _nan()
    iterations = 0
    status = "INVALID_ENERGY_PROFILE"

    if not energy_grid_finite or not energy_nondecreasing:
        # A binary search is invalid without a finite monotone profile.  Keep
        # the row and expose the failure in the machine-readable report.
        status = "INVALID_ENERGY_PROFILE"
    elif not empty_feasible:
        status = "EMPTY_TRIP_INFEASIBLE"
    elif full_feasible:
        q_max = rated_q
        status = "RATED_CAPACITY"
    else:
        # Case B: f(0)<=0 and f(Q)>0.  Use the exact energy inequality in the
        # bisection decision; tolerance is applied only to validation fields.
        lo, hi = 0.0, rated_q
        for iterations in range(1, max_iter + 1):
            mid = (lo + hi) / 2.0
            e_mid = roundtrip_energy(gtype, sid, mid, gt)
            if e_mid <= energy_limit:
                lo = mid
            else:
                hi = mid
            if hi - lo <= payload_tol:
                break
        q_max = float(lo)
        status = "ENERGY_LIMITED"

    if math.isfinite(q_max):
        q_max = float(np.clip(q_max, 0.0, rated_q))
        e_at_qmax = roundtrip_energy(gtype, sid, q_max, gt)
        margin = float(energy_limit - e_at_qmax)
        q_ratio = float(q_max / rated_q) if rated_q > 0 else _nan()
        qmax_feasible = bool(e_at_qmax <= energy_limit + energy_tol)
        if status == "RATED_CAPACITY":
            qmax_boundary_active = True
        else:
            qmax_boundary_active = bool(abs(margin) <= BOUNDARY_TOL)
    else:
        e_at_qmax = _nan()
        margin = _nan()
        q_ratio = _nan()
        qmax_feasible = False
        qmax_boundary_active = False

    plus_delta_applicable = status == "ENERGY_LIMITED" and math.isfinite(q_max)
    if plus_delta_applicable:
        q_plus = float(min(rated_q, q_max + delta))
        e_plus = roundtrip_energy(gtype, sid, q_plus, gt)
        q_plus_infeasible = bool(e_plus > energy_limit + energy_tol)
    else:
        q_plus = _nan()
        e_plus = _nan()
        q_plus_infeasible = None

    row: dict[str, Any] = {
        "sid": sid,
        "gtype": gtype,
        "rated_payload_kg": rated_q,
        "empty_roundtrip_energy_kwh": e_empty,
        "full_roundtrip_energy_kwh": e_full,
        "energy_limit_kwh": energy_limit,
        "empty_trip_feasible": empty_feasible,
        "full_load_feasible": full_feasible,
        "roundtrip_energy_nondecreasing": energy_nondecreasing,
        "q_max_kg": q_max,
        "q_max_ratio": q_ratio,
        "energy_at_qmax_kwh": e_at_qmax,
        "margin_at_qmax_kwh": margin,
        "qmax_feasible": qmax_feasible,
        "qmax_boundary_active": qmax_boundary_active,
        "qmax_plus_delta_kg": q_plus,
        "energy_at_qmax_plus_delta_kwh": e_plus,
        "qmax_plus_delta_infeasible": q_plus_infeasible,
        "capacity_status": status,
        "solver_method": (
            "rated_capacity_check"
            if status == "RATED_CAPACITY"
            else "bisection_monotone_energy"
            if status == "ENERGY_LIMITED"
            else "not_applicable"
        ),
        "iterations": int(iterations),
        "energy_grid_finite": energy_grid_finite,
        "qmax_plus_delta_check_applicable": plus_delta_applicable,
    }
    return row


def _json_value(value: Any) -> Any:
    """Convert NumPy scalars and NaN values into strict JSON values."""
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records_for_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _json_value(v) for k, v in row.items()} for row in rows]


def _failure_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        if not row["roundtrip_energy_nondecreasing"]:
            failures.append({"check": "roundtrip_energy_nondecreasing", "gtype": row["gtype"], "sid": row["sid"]})
        if not row["qmax_feasible"]:
            failures.append({"check": "qmax_feasible", "gtype": row["gtype"], "sid": row["sid"],
                             "status": row["capacity_status"], "margin_kwh": row["margin_at_qmax_kwh"]})
        if row["capacity_status"] == "ENERGY_LIMITED":
            if not row["qmax_boundary_active"]:
                failures.append({"check": "qmax_boundary_active", "gtype": row["gtype"], "sid": row["sid"]})
            if not row["qmax_plus_delta_infeasible"]:
                failures.append({"check": "qmax_plus_delta_infeasible", "gtype": row["gtype"], "sid": row["sid"],
                                 "qmax_plus_delta_kg": row["qmax_plus_delta_kg"],
                                 "energy_at_qmax_plus_delta_kwh": row["energy_at_qmax_plus_delta_kwh"]})
    return failures


def _make_report(rows: list[dict[str, Any]], summary: dict[str, Any], checks: dict[str, bool], failures: list[dict[str, Any]]) -> str:
    limited = [r for r in rows if r["capacity_status"] == "ENERGY_LIMITED"]
    all_table = [
        "| 机型 | 服务区 | Q (kg) | q_max (kg) | q_max/Q | 状态 | E(q_max) (kWh) | 裕量 (kWh) |",
        "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for r in rows:
        q = "—" if not math.isfinite(r["q_max_kg"]) else f"{r['q_max_kg']:.6f}"
        ratio = "—" if not math.isfinite(r["q_max_ratio"]) else f"{r['q_max_ratio']:.8f}"
        e = "—" if not math.isfinite(r["energy_at_qmax_kwh"]) else f"{r['energy_at_qmax_kwh']:.9f}"
        m = "—" if not math.isfinite(r["margin_at_qmax_kwh"]) else f"{r['margin_at_qmax_kwh']:.9f}"
        all_table.append(f"| {r['gtype']} | {r['sid']} | {r['rated_payload_kg']:.1f} | {q} | {ratio} | {r['capacity_status']} | {e} | {m} |")

    limited_table = [
        "| 机型 | 服务区 | Q_g (kg) | q_max (kg) | q_max/Q_g | E_limit (kWh) | 裕量 (kWh) | q_max+δ 越界 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in limited:
        limited_table.append(
            f"| {r['gtype']} | {r['sid']} | {r['rated_payload_kg']:.1f} | "
            f"{r['q_max_kg']:.6f} | {r['q_max_ratio']:.8f} | {r['energy_limit_kwh']:.9f} | "
            f"{r['margin_at_qmax_kwh']:.9f} | {'PASS' if r['qmax_plus_delta_infeasible'] else 'FAIL'} |"
        )

    checks_table = "\n".join(
        f"| {name} | {'PASS' if value else 'FAIL'} |" for name, value in checks.items()
    )
    failure_text = "\n".join(f"- `{f}`" for f in failures) if failures else "- 无"
    return f"""# Q1-2 最大安全载荷求解与验收

## 1. 范围与数学定义

本阶段对每个机型 `g ∈ {{A,B,C}}` 和服务区 `s ∈ {{S001,…,S015}}`，只考虑单服务区任务
`O01 → s → O01`，求连续质量意义下的最大安全载荷：

`q_max(g,s) = max {{q ∈ [0,Q_g] : E_trip(g,s,q) ≤ E_limit,g}}`

其中：

`E_trip(g,s,q) = E_O01→s(g,q) + E_s→O01(g,0)`

`E_limit,g = (1-rho_g) E_g^use`

返程载荷严格固定为 `q=0`。本阶段的 `q_max` 是能量安全条件下的连续质量边界；货箱不可拆分、体积、需求和组批在 Q1-3 单独处理。

## 2. 文献依据与边界

- Cheng, Adulyasak & Rousseau (2020) 将非线性能耗直接纳入无人机任务可行性约束。本实现借鉴这一建模思想，将 `E_trip(q) ≤ E_limit` 作为硬边界，没有复现其完整路径模型、能耗函数或精确算法。
- Zhang et al. (2021) 说明配送无人机能耗随机型、载荷和运行假设变化。本实现分别读取 A/B/C 的赛题参数，不使用统一经验系数，也不以文献参数替换赛题的 `L0`、`LF`、`Q` 或电池参数。
- Masmoudi et al. (2022) 说明多包裹载荷状态会影响配送决策。本实现先求连续质量能力边界，后续再在 Q1-3 处理离散货箱质量、体积和组合。

赛题公式与赛题数据优先于文献；本阶段没有修改 Q1-1 冻结的公共物理模型。

## 3. 求解方法

1. 对每个组合在 `[0,Q_g]` 上取 101 个载荷点，检查 `E_trip(q)` 有限且单调不减。
2. 若 `E_trip(Q_g) ≤ E_limit`，直接判为 `RATED_CAPACITY`，令 `q_max=Q_g`。
3. 若空载可行而额定满载不可行，在 `[0,Q_g]` 上用连续二分求解 `E_trip(q_max)=E_limit`。
4. 对每个结果检查 `q_max` 可行性；对能量受限组合再检查 `q_max+δ`（`δ=0.001 kg`）越过能量上限。

二分停止条件为载荷区间宽度不超过 `1e-6 kg`，最多 80 次迭代；能量判定容差为 `1e-8 kWh`。

## 4. 总体结果

| 指标 | 数量 |
| --- | ---: |
| 总组合 | {summary['total_pairs']} |
| 额定容量可行 (`RATED_CAPACITY`) | {summary['rated_capacity_pairs']} |
| 能量受限 (`ENERGY_LIMITED`) | {summary['energy_limited_pairs']} |
| 空载不可达 (`EMPTY_TRIP_INFEASIBLE`) | {summary['empty_trip_infeasible_pairs']} |
| 能量曲线非递减 | {summary['monotone_pairs']}/{summary['total_pairs']} |
| q_max 可行 | {summary['qmax_feasible_pairs']}/{summary['total_pairs']} |

## 5. 六个能量受限组合

""" + "\n".join(limited_table) + f"""

## 6. 45 组完整结果

""" + "\n".join(all_table) + f"""

## 7. 验收检查

| 检查项 | 结果 |
| --- | --- |
{checks_table}

能量受限组合的最大边界残差 `max(abs(margin_at_qmax))`：`{summary['max_abs_energy_boundary_margin_kwh']:.12g} kWh`。

失败明细：

{failure_text}

## 8. 参考文献

[1] Cheng C, Adulyasak Y, Rousseau L M. Drone routing with energy function: Formulation and exact algorithm. *Transportation Research Part B: Methodological*, 2020, 139: 364–387. DOI: 10.1016/j.trb.2020.06.011.

[2] Zhang J, Campbell J F, Sweeney D C, Hupman A C. Energy consumption models for delivery drones: A comparison and assessment. *Transportation Research Part D: Transport and Environment*, 2021, 90: 102668. DOI: 10.1016/j.trd.2020.102668.

[3] Masmoudi M A, Mancini S, Baldacci R, Kuo Y H. Vehicle routing problems with drones equipped with multi-package payload compartments. *Transportation Research Part E: Logistics and Transportation Review*, 2022, 164: 102757. DOI: 10.1016/j.tre.2022.102757.

## 9. 阶段结论

**{'PASS：可以冻结 Q1-2' if checks['all_checks_pass'] else 'FAIL：仍需修复'}**

若本报告为 PASS，下一阶段等待确认后进入 Q1-3：真实货箱离散组批、机型选择与 Q1 正式优化。
"""


def main() -> dict[str, Any]:
    # GTS is imported from the same cached public route module used by Q1-1;
    # load_transport_types is retained as a cross-check that the source table
    # contains exactly the three expected transport types.
    loaded = load_transport_types()
    if set(loaded) != {"A", "B", "C"}:
        raise RuntimeError(f"运输机型数据异常：{sorted(loaded)}")
    if set(GTS) != set(loaded):
        raise RuntimeError("公共 route.GTS 与 data.load_transport_types() 不一致")

    rows: list[dict[str, Any]] = []
    for sid in sid_list():
        for gtype in ("A", "B", "C"):
            rows.append(solve_single_service_qmax(gtype, sid, GTS[gtype]))

    total = len(rows)
    rated = sum(r["capacity_status"] == "RATED_CAPACITY" for r in rows)
    limited = sum(r["capacity_status"] == "ENERGY_LIMITED" for r in rows)
    empty_bad = sum(r["capacity_status"] == "EMPTY_TRIP_INFEASIBLE" for r in rows)
    invalid = sum(r["capacity_status"] == "INVALID_ENERGY_PROFILE" for r in rows)
    monotone = sum(bool(r["roundtrip_energy_nondecreasing"]) for r in rows)
    qmax_ok = sum(bool(r["qmax_feasible"]) for r in rows)
    limited_rows = [r for r in rows if r["capacity_status"] == "ENERGY_LIMITED"]
    max_abs_energy_boundary_margin = max(
        (abs(float(r["margin_at_qmax_kwh"])) for r in limited_rows
         if math.isfinite(r["margin_at_qmax_kwh"])),
        default=float("nan"),
    )
    expected_limited_pairs = {
        ("B", "S008"),
        ("C", "S002"),
        ("C", "S003"),
        ("C", "S004"),
        ("C", "S008"),
        ("C", "S012"),
    }
    actual_limited_pairs = {(r["gtype"], r["sid"]) for r in limited_rows}

    checks: dict[str, bool] = {
        "total_pairs_is_45": total == 45,
        "rated_capacity_pairs_is_39": rated == 39,
        "energy_limited_pairs_is_6": limited == 6,
        "energy_limited_pair_set_matches_q1_1": actual_limited_pairs == expected_limited_pairs,
        "empty_trip_infeasible_pairs_is_0": empty_bad == 0,
        "no_invalid_energy_profiles": invalid == 0,
        "roundtrip_energy_nondecreasing_all": monotone == total,
        "qmax_feasible_all": qmax_ok == total,
        "energy_limited_qmax_below_rated": all(
            r["q_max_kg"] < r["rated_payload_kg"] - PAYLOAD_TOL for r in limited_rows
        ),
        "energy_limited_boundary_active": all(
            bool(r["qmax_boundary_active"]) for r in limited_rows
        ),
        "energy_limited_plus_delta_infeasible": all(
            bool(r["qmax_plus_delta_infeasible"]) for r in limited_rows
        ),
        "qmax_values_in_range": all(
            (not math.isfinite(r["q_max_kg"]))
            or (-PAYLOAD_TOL <= r["q_max_kg"] <= r["rated_payload_kg"] + PAYLOAD_TOL)
            for r in rows
        ),
    }
    checks["all_checks_pass"] = all(checks.values())
    failures = _failure_records(rows)
    summary: dict[str, Any] = {
        "total_pairs": total,
        "rated_capacity_pairs": rated,
        "energy_limited_pairs": limited,
        "empty_trip_infeasible_pairs": empty_bad,
        "invalid_energy_profile_pairs": invalid,
        "monotone_pairs": monotone,
        "qmax_feasible_pairs": qmax_ok,
        "max_abs_energy_boundary_margin_kwh": max_abs_energy_boundary_margin,
    }

    frame = pd.DataFrame(rows)
    frame.to_csv(RES / "q1_capacity.csv", index=False, encoding="utf-8-sig")
    report: dict[str, Any] = {
        "phase": "Q1-2",
        "scope": "单服务区连续最大安全载荷能力边界",
        "total_pairs": total,
        "rated_capacity_pairs": rated,
        "energy_limited_pairs": limited,
        "empty_trip_infeasible_pairs": empty_bad,
        "invalid_energy_profile_pairs": invalid,
        "all_checks_pass": checks["all_checks_pass"],
        "checks": checks,
        "summary": summary,
        "energy_limited_details": _records_for_json(limited_rows),
        "failures": _records_for_json(failures),
        "parameters": {
            "grid_points": GRID_POINTS,
            "payload_tol_kg": PAYLOAD_TOL,
            "energy_tol_kwh": ENERGY_TOL,
            "boundary_tol_kwh": BOUNDARY_TOL,
            "max_iter": MAX_ITER,
            "delta_kg": DELTA_KG,
        },
        "literature_boundary": {
            "Cheng_2020": "借鉴非线性能耗直接进入可行性约束，不照搬完整路径模型或参数。",
            "Zhang_2021": "保留 A/B/C 机型和载荷差异，不用文献参数替换赛题参数。",
            "Masmoudi_2022": "将连续质量能力边界与 Q1-3 的离散货箱组批分层。",
        },
    }
    with (RES / "q1_capacity.json").open("w", encoding="utf-8") as f:
        json.dump({k: _json_value(v) if not isinstance(v, (dict, list)) else v for k, v in report.items()}, f,
                  ensure_ascii=False, indent=2, allow_nan=False)
    (RES / "q1_capacity_report.md").write_text(
        _make_report(rows, summary, checks, failures), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    main()
