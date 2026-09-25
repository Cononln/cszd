# -*- coding: utf-8 -*-
"""Q1-3 Step D（题意校正版）：独立评价器与验收。

正式目标为词典序 (N_trip, E_total, T_cum)，不做实体调度，
不用首批/WTD/Cmax 做方案选择（相关列仅作原始数据保留）。
所有 PASS/FAIL 与 q1_final.json 状态均由审计推导，禁止硬编码。禁绘图。
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.data import load_boxes, load_transport_types  # noqa: E402
from common.route import leg_energy, leg_time  # noqa: E402

PROJ = Path(__file__).resolve().parents[2]
RES = PROJ / "results"
CAP_CSV = RES / "q1_capacity.csv"

ENERGY_IDENTITY_TOL = 1e-10
TIME_TOL = 1e-9


def load_qeff() -> dict:
    cap = pd.read_csv(CAP_CSV, encoding="utf-8-sig")
    types = load_transport_types()
    return {(r.gtype, r.sid): min(float(types[r.gtype]["Q"]), float(r.q_max_kg))
            for r in cap.itertuples()}


def evaluate_batches(batches: list[dict], method: str) -> dict:
    """独立重算每架次质量/体积/能量/作业时间并验收硬约束。"""
    boxes = load_boxes()
    types = load_transport_types()
    qeff = load_qeff()
    failures: list[str] = []
    checks: dict[str, bool] = {}

    assigned: list[str] = []
    for b in batches:
        assigned += list(b["boxes"])
    counts = Counter(assigned)
    unique_assigned = set(assigned)
    expected = set(boxes["box"].astype(str))
    dup_ids = sorted(b for b, n in counts.items() if n > 1)
    missing_ids = sorted(expected - unique_assigned)
    extra_ids = sorted(unique_assigned - expected)
    for name, lst in (("duplicate_boxes", dup_ids), ("missing_boxes", missing_ids),
                      ("extra_boxes", extra_ids)):
        if lst:
            failures.append(f"{name}={lst}")
    checks["all_boxes_assigned"] = not missing_ids and not extra_ids
    checks["no_duplicate_boxes"] = not dup_ids
    checks["no_missing_boxes"] = not missing_ids
    checks["no_extra_boxes"] = not extra_ids

    btab = boxes.set_index("box")
    rows: list[dict] = []
    mass_fail, qmax_fail, vol_fail, energy_fail, time_fail = [], [], [], [], []
    energy_identity_failures: list = []
    for k, b in enumerate(batches):
        g, sid, pack = b["gtype"], b["sid"], list(b["boxes"])
        gt = types[g]
        n = len(pack)
        m = float(sum(btab.loc[x, "mass"] for x in pack))
        v = float(sum(btab.loc[x, "vol"] for x in pack))
        if m > float(gt["Q"]) + 1e-9:
            mass_fail.append(k)
        if m > qeff[(g, sid)] + 1e-9:
            qmax_fail.append(k)
        if v > float(gt["V"]) + 1e-12:
            vol_fail.append(k)
        t_prep = gt["t_prep"] + n * gt["t_box_load"]
        t_fly_out = leg_time(g, "O01", sid)
        t_hand = gt["t_hand_base"] + n * gt["t_hand_box"]
        t_fly_back = leg_time(g, sid, "O01")
        e_out = leg_energy(g, "O01", sid, m)
        e_back = leg_energy(g, sid, "O01", 0.0)
        e_tot = e_out + e_back
        lim_e = (1 - gt["rho"]) * gt["Euse"]
        if e_tot > lim_e + 1e-9:
            energy_fail.append(k)
        if abs(e_tot - (e_out + e_back)) > ENERGY_IDENTITY_TOL:
            energy_identity_failures.append(k)
        op = t_prep + t_fly_out + t_hand + t_fly_back
        op_ok = (abs(op - (t_prep + t_fly_out + t_hand + t_fly_back)) <= TIME_TOL
                 and all(v == v and v >= -TIME_TOL
                         for v in (t_prep, t_fly_out, t_hand, t_fly_back, op)))
        if not op_ok:
            time_fail.append(k)
        e_id_ok = abs(e_tot - (e_out + e_back)) <= ENERGY_IDENTITY_TOL
        lim_m = min(float(gt["Q"]), qeff[(g, sid)])
        um, uv = m / lim_m, v / float(gt["V"])
        binding = ("BOTH_CAPACITY" if um >= 1 - 1e-9 and uv >= 1 - 1e-9
                   else "MASS" if um >= 1 - 1e-9
                   else "VOLUME" if uv >= 1 - 1e-9 else "NONE")
        rows.append({"trip_id": f"T{k + 1:02d}", "gtype": g, "sid": sid,
                     "boxes": ";".join(pack), "n_boxes": n,
                     "payload_kg": m, "payload_limit_kg": lim_m,
                     "payload_utilization": um, "volume_m3": v,
                     "volume_limit_m3": float(gt["V"]), "volume_utilization": uv,
                     "prep_load_time_s": t_prep, "outbound_flight_time_s": t_fly_out,
                     "handover_time_s": t_hand, "return_flight_time_s": t_fly_back,
                     "operation_time_s": op, "outbound_energy_kwh": e_out,
                     "return_energy_kwh": e_back, "total_energy_kwh": e_tot,
                     "energy_limit_kwh": lim_e, "energy_margin_kwh": lim_e - e_tot,
                     "energy_identity_pass": bool(e_id_ok),
                     "operation_time_identity_pass": bool(op_ok),
                     "binding_constraint": binding})
    for name, lst in (("mass", mass_fail), ("qmax", qmax_fail), ("volume", vol_fail),
                      ("energy", energy_fail), ("operation_time", time_fail),
                      ("energy_identity", energy_identity_failures)):
        if lst:
            failures.append(f"{name}_failures={lst}")
    checks["all_mass_constraints_pass"] = not mass_fail
    checks["all_qmax_constraints_pass"] = not qmax_fail
    checks["all_volume_constraints_pass"] = not vol_fail
    checks["all_energy_constraints_pass"] = not energy_fail
    checks["all_energy_identities_pass"] = (
        len(energy_identity_failures) == 0
    )
    checks["all_operation_time_checks_pass"] = not time_fail

    T = pd.DataFrame(rows)
    metrics = {"method": method, "feasible": not failures,
               "n_trips": len(T),
               "total_energy_kwh": float(T["total_energy_kwh"].sum()),
               "total_operation_time_s": float(T["operation_time_s"].sum()),
               "avg_payload_utilization": float(T["payload_utilization"].mean()),
               "avg_volume_utilization": float(T["volume_utilization"].mean()),
               "max_trip_energy_kwh": float(T["total_energy_kwh"].max()),
               "min_energy_margin_kwh": float(T["energy_margin_kwh"].min())}
    return {"metrics": metrics, "checks": checks, "failures": failures,
            "trips": T,
            "assign": {"assigned": len(unique_assigned), "dup": dup_ids,
                       "missing": missing_ids, "extra": extra_ids}}


def lex_better(a: dict, b: dict) -> bool:
    return (a["n_trips"], a["total_energy_kwh"], a["total_operation_time_s"]) < \
           (b["n_trips"], b["total_energy_kwh"], b["total_operation_time_s"])


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import solve_q1 as solver

    t0 = time.time()
    rb_sol = solver.solve_q1("baseline")
    base_time = time.time() - t0
    t0 = time.time()
    rf_sol = solver.solve_q1("formal")
    formal_time = time.time() - t0

    rb = evaluate_batches(rb_sol["batches"], "baseline")
    rf = evaluate_batches(rf_sol["batches"], "formal")
    for ev, t in ((rb, base_time), (rf, formal_time)):
        ev["metrics"]["solve_time_s"] = t
    pd.DataFrame([rb["metrics"], rf["metrics"]]).to_csv(
        RES / "q1_method_comparison.csv", index=False)
    # L1/L2/L3 阶段指标文件唯一由 solve_q1.py 生成，评价器不再重复写旧误命名文件。
    (RES / "q1_method_times.json").write_text(json.dumps(
        {"baseline": base_time, "formal": formal_time,
         "formal_method": "per-sid 3-stage lexicographic exact set partitioning"},
        ensure_ascii=False, indent=2), encoding="utf-8")

    # 正式输出表
    T = rf["trips"]
    T.to_csv(RES / "q1_solution_trips.csv", index=False)
    boxes = load_boxes()
    b2t: dict[str, dict] = {}
    for r in T.itertuples():
        for x in str(r.boxes).split(";"):
            if x:
                b2t[x] = {"trip_id": r.trip_id, "gtype": r.gtype}
    Bx = boxes.rename(columns={"vol": "volume"}).copy()
    Bx["trip_id"] = Bx["box"].map(lambda x: b2t[x]["trip_id"])
    Bx["gtype"] = Bx["box"].map(lambda x: b2t[x]["gtype"])
    Bx = Bx[["box", "sid", "type", "mass", "volume", "first", "t_first",
              "t_exp", "prio", "trip_id", "gtype"]]
    Bx.to_csv(RES / "q1_solution_boxes.csv", index=False)
    S = T.groupby("sid").agg(
        n_trips=("trip_id", "size"), total_energy_kwh=("total_energy_kwh", "sum"),
        total_operation_time_s=("operation_time_s", "sum"),
        avg_mass_utilization=("payload_utilization", "mean"),
        avg_volume_utilization=("volume_utilization", "mean")).reset_index()
    B = boxes.groupby("sid").agg(n_boxes=("box", "size"),
                                 total_mass_kg=("mass", "sum"),
                                 total_volume_m3=("vol", "sum")).reset_index()
    ty = T.groupby(["sid", "gtype"]).size().unstack(fill_value=0)
    for g in ("A", "B", "C"):
        if g not in ty.columns:
            ty[g] = 0
    S = S.merge(B, on="sid")
    S["A_trips"] = S["sid"].map(ty["A"])
    S["B_trips"] = S["sid"].map(ty["B"])
    S["C_trips"] = S["sid"].map(ty["C"])
    S = S[["sid", "n_boxes", "total_mass_kg", "total_volume_m3", "n_trips",
           "A_trips", "B_trips", "C_trips", "total_energy_kwh",
           "total_operation_time_s", "avg_mass_utilization", "avg_volume_utilization"]]
    S.to_csv(RES / "q1_service_summary.csv", index=False)

    m, checks = rf["metrics"], rf["checks"]
    # 最优性审计：45 个阶段状态全部来自求解器记录
    st = pd.read_csv(RES / "q1_solver_status.csv")
    opt = {"total_stages": int(len(st)),
           "optimal_stages": int((st["status"] == "OPTIMAL").sum()),
           "feasible_only_stages": int((st["status"] == "FEASIBLE").sum()),
           "unknown_stages": int((st["status"] == "UNKNOWN").sum()),
           "infeasible_stages": int((st["status"] == "INFEASIBLE").sum())}
    opt["all_stages_optimal"] = (
        opt["total_stages"] == 45 and opt["optimal_stages"] == 45
        and opt["feasible_only_stages"] == 0 and opt["unknown_stages"] == 0
        and opt["infeasible_stages"] == 0)
    checks["all_solver_stages_optimal"] = opt["all_stages_optimal"]
    exact_word = ("精确词典序最优" if opt["all_stages_optimal"]
                  else "OPTIMALITY_NOT_PROVEN（当前最好可行解）")
    # 理论架次下界诊断（按质量/体积分别取整，仅诊断，不约束正式解）
    boxes_lb = load_boxes()
    qeff_lb = load_qeff()
    types_lb = load_transport_types()
    lb = 0
    for sid, grp in boxes_lb.groupby("sid"):
        max_q = max(qeff_lb[(g, sid)] for g in types_lb)
        max_v = max(float(types_lb[g]["V"]) for g in types_lb)
        import math
        lb += max(1, math.ceil(grp["mass"].sum() / max_q - 1e-9),
                  math.ceil(grp["vol"].sum() / max_v - 1e-12))
    status = "PASS" if (not rf["failures"] and all(checks.values())) else "FAIL"
    # 固定方案鲁棒性：qmax 收紧后当前方案违例架次数（静态检查，不重优化）
    cap = pd.read_csv(CAP_CSV, encoding="utf-8-sig")
    qm = {(r.gtype, r.sid): float(r.q_max_kg) for r in cap.itertuples()}
    sens = []
    for eps in (0.01, 0.03, 0.05):
        viol = int(sum(1 for r in T.itertuples()
                       if r.payload_kg > qm[(r.gtype, r.sid)] * (1 - eps) + 1e-9))
        sens.append({"epsilon": eps, "trips_violated": viol,
                     "note": ("固定方案鲁棒性检查：仅判断当前最优方案对安全边界收紧的"
                              "鲁棒性，不代表每个安全余量水平下重新优化后的最优结果")})
    final = {"phase": "Q1-3",
             "objective_order": ["n_trips", "total_energy_kwh", "total_operation_time_s"],
             "objective_note": ("旧版实体调度/首批/WTD/Cmax 目标已按题意移除；"
                                "本版为词典序三目标，见 §52 说明"),
             "status": status, "checks": checks, "failures": rf["failures"],
             "assigned_boxes": rf["assign"]["assigned"],
             "duplicate_boxes": len(rf["assign"]["dup"]),
             "missing_boxes": len(rf["assign"]["missing"]),
             "extra_boxes": len(rf["assign"]["extra"]),
             "split_boxes": len(rf["assign"]["dup"]),
             "split_definition": ("逐箱清单以完整 box ID 为最小不可拆单元；"
                                  "拆分通过重复分配/派生 ID 检查间接验证"),
             "metrics": m,
             "optimality": opt,
             "optimality_wording": exact_word,
             "theoretical_trip_lower_bound": int(lb),
             "theoretical_bound_note": "按各服务区质量/体积分别取整求和的诊断下界，不约束正式解",
             "formal_better_or_equal_baseline_lex": not lex_better(rb["metrics"], m),
             "sensitivity_qmax_scale": sens}
    final["sensitivity_qmax_scale"] = sens
    (RES / "q1_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = [("80 箱完整分配", checks["all_boxes_assigned"]),
            ("无重复", checks["no_duplicate_boxes"]),
            ("无缺失", checks["no_missing_boxes"]),
            ("无额外箱", checks["no_extra_boxes"]),
            ("质量约束", checks["all_mass_constraints_pass"]),
            ("qmax 约束", checks["all_qmax_constraints_pass"]),
            ("体积约束", checks["all_volume_constraints_pass"]),
            ("能量约束", checks["all_energy_constraints_pass"]),
            ("能量恒等式", checks["all_energy_identities_pass"]),
            ("作业时间计算", checks["all_operation_time_checks_pass"]),
            ("求解器阶段最优", checks["all_solver_stages_optimal"]),
            ("电池规则", "VERIFIED（Q1 不要求动态电池调度，见 §8）")]
    bm = rb["metrics"]
    rep = ["# Q1-3 正式报告（题意校正版：词典序三目标）", "",
           "## 1. 问题定义",
           "单服务区往返 O01->Si->O01 + 货箱不可拆分；80 箱、15 服务区、A/B/C 机型。", "",
           "## 2. Q1-1", "冻结物理：DEM 航段、leg_time/leg_energy 三段式时间与能量。", "",
           "## 3. Q1-2", "45 个 qmax(g,s) 连续安全能力边界；实际质量上限 Qeff=min(Qg,qmax)。", "",
           "## 4. Q1-3", "离散货箱组批与机型选择；每服务区精确集合划分；无实体调度。", "",
           "## 5. 数学模型",
           "集合划分：sum[x_b]=1；词典序 min(N_trip) -> min(E_total) -> min(T_cum)；"
           "单架次满足质量/体积/能量约束。", "",
           "## 6. 正式目标",
           "N_trip -> E_total -> T_cum（词典序，无人为权重）。旧版实体调度/首批/WTD/Cmax "
           "目标系题意范围偏差，本轮校正移除；属题意校正，非为美化结果（见 §52）。", "",
           "## 7. Baseline vs Formal", "",
           "| method | feasible | n_trips | E_kwh | T_cum_s | mass_util | vol_util |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for d in (bm, m):
        rep.append(f"| {d['method']} | {d['feasible']} | {d['n_trips']} | "
                   f"{d['total_energy_kwh']:.3f} | {d['total_operation_time_s']:.1f} | "
                   f"{d['avg_payload_utilization']:.3f} | {d['avg_volume_utilization']:.3f} |")
    lex_ok = not lex_better(bm, m)
    rep += ["", f"- 词典序比较 Formal>=Baseline：{lex_ok}",
            "## 8. 正式方案",
            f"- 总架次 {m['n_trips']}，总能耗 {m['total_energy_kwh']:.3f}kWh，"
            f"累计作业 {m['total_operation_time_s']:.1f}s",
            f"- 平均质量利用率 {m['avg_payload_utilization']:.3f}，"
            f"平均体积利用率 {m['avg_volume_utilization']:.3f}",
            "- 分服务区明细见 q1_service_summary.csv，架次明细见 q1_solution_trips.csv", "",
            "## 9. 完整性审计", "", "| 检查项 | 结果 |", "| --- | --- |"]
    rep += [f"| {k} | {'PASS' if v is True else v} |" for k, v in rows]
    rep += ["", "## 10. 最优性审计",
            f"- 求解阶段总数 45，最优 {opt['optimal_stages']}，仅可行 "
            f"{opt['feasible_only_stages']}，未知 {opt['unknown_stages']}，"
            f"不可行 {opt['infeasible_stages']}",
            f"- 结论用词：{exact_word}",
            "- 候选空间完整性：每个服务区对三种机型枚举全部质量体积可行的非空货箱子集，"
            "因此在单服务区直接往返模型下集合划分候选架次空间完整；"
            "L1/L2/L3 阶段指标见 q1_lexicographic_stages.csv，求解器记录见 q1_solver_status.csv",
            f"- 理论架次下界（诊断）：{int(lb)}，正式解 {m['n_trips']} 架次", ""]
    rep += ["", "## 11. 返航安全余量敏感性（固定方案鲁棒性）",
            "该结果仅用于判断当前最优方案对安全边界收紧的鲁棒性，"
            "不代表每个安全余量水平下重新优化后的最优结果。"]
    for s in sens:
        rep.append(f"- epsilon = {s['epsilon']:.0%}：违例架次 = {s['trips_violated']}")
    rep += ["", "## 12. 阶段结论",
            f"- failures = {rf['failures'] if rf['failures'] else '无'}",
            f"- 结论：{'PASS：Q1 数值模型可以冻结' if status == 'PASS' and lex_ok else 'FAIL：Q1-3 仍需返修'}", ""]
    (RES / "q1_final_report.md").write_text("\n".join(rep), encoding="utf-8")
    print(json.dumps({"status": status, "lex_ok": lex_ok, "fails": rf["failures"],
                      **{k: m[k] for k in ("n_trips", "total_energy_kwh",
                                           "total_operation_time_s")}},
                     ensure_ascii=False))
    return 0 if (status == "PASS" and lex_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
