# -*- coding: utf-8 -*-
"""问题一：单点往返运输能力与货箱组批方案。

(1) 三种机型在各服务区的最大安全载荷  —— 能量方程根 + 载质量上限
(2) 货箱不可拆分、每箱一次、载质量/体积/返航余量约束下的组批方案 —— MILP
(3) 架次数 -> 总能耗 -> 累计作业时间的字典序优化与权衡分析
(4) 返航安全余量 rho 的灵敏度分析

输出：results/q1_*.csv / .json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import G, KWH_J, RES
from common.data import load_nodes, load_boxes, load_transport_types, sid_list
from common.dem import get_dem
from common.physics import Leg, equiv_range, ops_height

DEM = get_dem()
NODES = load_nodes().set_index("id")
BOXES = load_boxes()
GTS = load_transport_types()
SIDS = sid_list()
E_SCALE = 1_000_000          # 能耗整数化刻度（kWh -> 1e-6 kWh）
V_SCALE = 100_000            # 体积整数化刻度（m^3 -> 1e-5 m^3）


# ==================================================================== 航段
def round_trip_legs(sid):
    """O01 -> Si -> O01 两条航段。"""
    o, s = NODES.loc["O01"], NODES.loc[sid]
    l1 = Leg("O01", sid, o.lon, o.lat, ops_height(o), s.lon, s.lat, ops_height(s))
    l2 = Leg(sid, "O01", s.lon, s.lat, ops_height(s), o.lon, o.lat, ops_height(o))
    return l1, l2


def trip_energy(g, sid, q):
    """单点往返架次总能耗 (kWh)，去程载荷 q、返程空载。"""
    gt = GTS[g]
    l1, l2 = round_trip_legs(sid)
    return l1.energy(gt, q) + l2.energy(gt, 0.0)


def trip_energy_table(g, sid, qmax_int):
    """整数载荷 -> 能耗 的精确表（kWh），用于 MILP 中的 AddElement。"""
    return np.array([trip_energy(g, sid, q) for q in range(int(qmax_int) + 1)])


def max_safe_payload(g, sid, rho=None, tol=1e-6):
    """最大安全载荷 (kg)。

    求解 E(q) <= (1-rho) E_use 的最大 q，再与机型最大载货质量取小。
    E(q) 关于 q 单调递增（L(q) 递减且爬升质量随 q 增加），故可直接二分。
    """
    gt = GTS[g]
    rho_ = gt["rho"] if rho is None else rho
    lim = (1 - rho_) * gt["Euse"]
    E0 = trip_energy(g, sid, 0.0)
    if E0 > lim:                      # 空载即超限：无可用载荷
        return 0.0, lim, E0
    if trip_energy(g, sid, gt["Q"]) <= lim:
        return gt["Q"], lim, trip_energy(g, sid, gt["Q"])
    lo, hi = 0.0, gt["Q"]
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if trip_energy(g, sid, mid) <= lim:
            lo = mid
        else:
            hi = mid
    return lo, lim, trip_energy(g, sid, lo)


# ==================================================================== MILP
def solve_batching(masses, vols, Qcap, Vcap, Etab=None, w_trip=1.0,
                   w_energy=0.0, time_limit=60.0, log=False):
    """单服务区-单机型组批 MILP。

    masses/vols: 该服务区货箱的质量与体积列表
    Qcap/Vcap  : 本架次可用载质量 (kg) 与可用装载体积 (m^3)
    Etab       : 整数载荷 -> 能耗表（用于二级目标）
    w_trip/w_energy: 加权目标系数（字典序通过极大权重实现）
    """
    n = len(masses)
    if n == 0:
        return [], 0, 0.0
    Qcap_i = int(np.floor(Qcap + 1e-9))
    Vcap_i = int(np.floor(Vcap * V_SCALE + 1e-9))
    m_i = [int(round(m)) for m in masses]
    v_i = [int(round(v * V_SCALE)) for v in vols]

    # 每箱单独一架次必然可行（需已校验单箱不超过容量）
    T = n
    model = cp_model.CpModel()
    x = {(b, t): model.NewBoolVar(f"x{b}_{t}") for b in range(n) for t in range(T)}
    y = [model.NewBoolVar(f"y{t}") for t in range(T)]
    q = [model.NewIntVar(0, Qcap_i, f"q{t}") for t in range(T)]

    for b in range(n):
        model.AddExactlyOne(x[b, t] for t in range(T))
    for t in range(T):
        model.Add(q[t] == sum(m_i[b] * x[b, t] for b in range(n)))
        model.Add(q[t] <= Qcap_i * y[t])
        model.Add(sum(m_i[b] * x[b, t] for b in range(n)) <= Qcap_i * y[t])
        model.Add(sum(v_i[b] * x[b, t] for b in range(n)) <= Vcap_i * y[t])
    # 对称性破除：架次按序启用
    for t in range(T - 1):
        model.Add(y[t] >= y[t + 1])

    obj = int(round(w_trip * 1_000_000)) * sum(y)
    if Etab is not None and w_energy > 0:
        e_t = [model.NewIntVar(0, int(Etab.max() * E_SCALE) + 1, f"e{t}") for t in range(T)]
        for t in range(T):
            model.AddElement(q[t], [int(round(v * E_SCALE)) for v in Etab], e_t[t])
        obj = obj + int(round(w_energy * 1_000_000 / E_SCALE)) * sum(e_t)
    model.Minimize(obj)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    if not log:
        solver.parameters.log_search_progress = False
    st = solver.Solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, None

    trips = []
    for t in range(T):
        if solver.Value(y[t]) == 1:
            trips.append([b for b in range(n) if solver.Value(x[b, t]) == 1])
    M = len(trips)
    E = sum(float(Etab[int(round(solver.Value(q[t])))]) for t in range(T) if solver.Value(y[t]) == 1) \
        if Etab is not None else None
    return trips, M, E


def lexicographic_batch(sid, g, rho=None):
    """字典序：最少架次 -> 最小总能耗 -> 最短累计作业时间。"""
    gt = GTS[g]
    sub = BOXES[BOXES["sid"] == sid]
    masses = sub["mass"].tolist()
    vols = sub["vol"].tolist()
    qmax, lim, E0 = max_safe_payload(g, sid, rho=rho)

    # 单箱可行性检查：必须保证该站任一货箱都能单独成行，否则该机型在此站不可用
    m_max = max(masses)
    if qmax < m_max - 1e-9:
        return dict(sid=sid, g=g, qmax=qmax, limit=lim, Vcap=gt["V"],
                    trips=[], n_trips=None, energy=None, boxes=sub,
                    feasible=False, reason="安全载荷不足以携带最重货箱", E0=E0)
    for m, v, bx in zip(masses, vols, sub["box"]):
        if v > gt["V"] + 1e-12:
            raise RuntimeError(f"{bx} 单箱体积 {v} 超过 {g} 可用装载体积 {gt['V']}")

    # 阶段 1：最少架次
    trips1, M1, _ = solve_batching(masses, vols, qmax, gt["V"], None, 1.0, 0.0)
    if trips1 is None:
        return None
    # 阶段 2：固定架次数下最小化总能耗（凸函数 -> 均衡装载）
    T = len(masses)
    Etab = trip_energy_table(g, sid, int(np.floor(qmax)) if qmax < gt["Q"] else gt["Q"])

    model = cp_model.CpModel()
    n = len(masses)
    Qcap_i = int(np.floor(qmax + 1e-9))
    Vcap_i = int(np.floor(gt["V"] * V_SCALE + 1e-9))
    m_i = [int(round(m)) for m in masses]
    v_i = [int(round(v * V_SCALE)) for v in vols]
    x = {(b, t): model.NewBoolVar(f"x{b}_{t}") for b in range(n) for t in range(M1)}
    qv = [model.NewIntVar(0, Qcap_i, f"q{t}") for t in range(M1)]
    ev = [model.NewIntVar(0, int(Etab.max() * E_SCALE) + 10, f"e{t}") for t in range(M1)]
    for b in range(n):
        model.AddExactlyOne(x[b, t] for t in range(M1))
    for t in range(M1):
        model.Add(qv[t] == sum(m_i[b] * x[b, t] for b in range(n)))
        model.Add(sum(v_i[b] * x[b, t] for b in range(n)) <= Vcap_i)
        model.AddElement(qv[t], [int(round(v * E_SCALE)) for v in Etab], ev[t])
    model.Minimize(sum(ev))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 120
    solver.parameters.num_search_workers = 8
    st = solver.Solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        trips2, M2, E2 = trips1, M1, None
    else:
        trips2 = [[b for b in range(n) if solver.Value(x[b, t]) == 1] for t in range(M1)]
        E2 = sum(float(Etab[int(round(solver.Value(qv[t])))]) for t in range(M1))
    return dict(sid=sid, g=g, qmax=qmax, limit=lim, Vcap=gt["V"],
                trips=trips2, n_trips=M1, energy=E2, boxes=sub)


def build_trip_records(res):
    """把 MILP 结果转成提交表记录（架次编号/服务区/机型/货箱列表/...）。"""
    gt = GTS[res["g"]]
    g, sid = res["g"], res["sid"]
    if not res.get("feasible", True):
        return []
    sub = res["boxes"].reset_index(drop=True)
    l1, l2 = round_trip_legs(sid)
    t_fly = l1.time(gt) + l2.time(gt)
    recs = []
    for k, idxs in enumerate(res["trips"], 1):
        boxes = sub.iloc[idxs]
        q = float(boxes["mass"].sum())
        v = float(boxes["vol"].sum())
        E = trip_energy(g, sid, q)
        n_box = len(boxes)
        T = gt["t_prep"] + n_box * gt["t_box_load"] + t_fly + gt["t_hand_base"] + n_box * gt["t_hand_box"]
        recs.append(dict(
            trip_id=f"Q1-{sid}-{g}-{k:02d}", sid=sid, gtype=g,
            boxes="|".join(boxes["box"].tolist()),
            n_box=n_box, mass=round(q, 2), vol=round(v, 4),
            rt_time=round(T, 2), energy=round(E, 4),
            soc_end=round((1 - E / gt["Euse"]) * 100, 2)))
    return recs


# ==================================================================== 主流程
def main():
    out = {}

    # ---------------- (1) 最大安全载荷
    rows = []
    for sid in SIDS:
        for g in ["A", "B", "C"]:
            q, lim, E = max_safe_payload(g, sid)
            gt = GTS[g]
            l1, l2 = round_trip_legs(sid)
            rows.append(dict(
                sid=sid, gtype=g, gname=gt["name"],
                dist=round(l1.d, 1), zmax=round(l1.zmax, 1),
                z_cruise=round(l1.z_cruise, 1), h_up=round(l1.h_up, 1),
                Q_model=gt["Q"], q_max=round(q, 3),
                energy_at_qmax=round(trip_energy(g, sid, q), 4),
                energy_limit=round(lim, 4),
                energy_slack=round(lim - trip_energy(g, sid, q), 4),
                binding="能量" if q < gt["Q"] - 1e-6 else "载质量",
                V=gt["V"], rt_flight_s=round(l1.time(gt) + l2.time(gt), 1)))
    q1a = pd.DataFrame(rows)
    q1a.to_csv(RES / "q1_max_payload.csv", index=False, encoding="utf-8-sig")
    out["max_payload"] = q1a.to_dict("records")

    # ---------------- (2)(3) 组批
    all_recs, summary = [], []
    for sid in SIDS:
        for g in ["A", "B", "C"]:
            res = lexicographic_batch(sid, g)
            recs = build_trip_records(res)
            all_recs.extend(recs)
            tot_E = sum(r["energy"] for r in recs)
            tot_T = sum(r["rt_time"] for r in recs)
            summary.append(dict(sid=sid, gtype=g, n_trips=res["n_trips"],
                                qmax=round(res["qmax"], 3),
                                total_mass=round(sum(r["mass"] for r in recs), 2),
                                total_vol=round(sum(r["vol"] for r in recs), 4),
                                total_energy=round(tot_E, 4),
                                cum_time=round(tot_T, 1),
                                cum_time_h=round(tot_T / 3600, 3),
                                max_trip_time=round(max(r["rt_time"] for r in recs), 1),
                                mean_load=round(sum(r["mass"] for r in recs) / res["n_trips"], 2),
                                energy_per_kg=round(tot_E / max(sum(r["mass"] for r in recs), 1e-9), 5)))
    q1b = pd.DataFrame(all_recs)
    q1s = pd.DataFrame(summary)
    q1b.to_csv(RES / "q1_batching_trips.csv", index=False, encoding="utf-8-sig")
    q1s.to_csv(RES / "q1_batching_summary.csv", index=False, encoding="utf-8-sig")
    out["batching"] = q1b.to_dict("records")
    out["summary"] = q1s.to_dict("records")

    # ---------------- 机型方案汇总（每服务区选一种机型）
    best = q1s.sort_values(["sid", "n_trips", "total_energy", "cum_time"]) \
              .groupby("sid").first().reset_index()
    best.to_csv(RES / "q1_best_per_sid.csv", index=False, encoding="utf-8-sig")
    out["best_per_sid"] = best.to_dict("records")

    # ---------------- (4) 灵敏度：返航安全余量
    sens = []
    for rho in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
        for sid in SIDS:
            for g in ["A", "B", "C"]:
                q, lim, _ = max_safe_payload(g, sid, rho=rho)
                sens.append(dict(rho=rho, sid=sid, gtype=g, q_max=round(q, 3),
                                 binding="能量" if q < GTS[g]["Q"] - 1e-6 else "载质量",
                                 limit=round(lim, 3)))
    pd.DataFrame(sens).to_csv(RES / "q1_rho_sensitivity.csv", index=False, encoding="utf-8-sig")

    # rho 变化对组批的影响
    sens_batch = []
    for rho in [0.10, 0.20, 0.30, 0.40]:
        for sid in SIDS:
            for g in ["A", "B", "C"]:
                res = lexicographic_batch(sid, g, rho=rho)
                recs = build_trip_records(res)
                tot_E = sum(r["energy"] for r in recs)
                sens_batch.append(dict(rho=rho, sid=sid, gtype=g,
                                       n_trips=res["n_trips"],
                                       feasible=res.get("feasible", True),
                                       qmax=round(res["qmax"], 3),
                                       total_energy=round(tot_E, 4)))
    pd.DataFrame(sens_batch).to_csv(RES / "q1_rho_batching.csv", index=False, encoding="utf-8-sig")

    # ---------------- 汇总统计
    tot = dict(
        n_boxes=len(BOXES),
        total_mass=float(BOXES["mass"].sum()),
        total_vol=float(BOXES["vol"].sum()),
        trips_A=int(q1s[q1s.gtype == "A"]["n_trips"].sum()),
        trips_B=int(q1s[q1s.gtype == "B"]["n_trips"].sum()),
        trips_C=int(q1s[q1s.gtype == "C"]["n_trips"].sum()),
        trips_best=int(best["n_trips"].sum()),
        energy_best=round(float(best["total_energy"].sum()), 4),
        cum_time_best_h=round(float(best["cum_time_h"].sum()), 3),
        energy_A=round(float(q1s[q1s.gtype == "A"]["total_energy"].sum()), 4),
        energy_B=round(float(q1s[q1s.gtype == "B"]["total_energy"].sum()), 4),
        energy_C=round(float(q1s[q1s.gtype == "C"]["total_energy"].sum()), 4),
        cum_h_A=round(float(q1s[q1s.gtype == "A"]["cum_time_h"].sum()), 3),
        cum_h_B=round(float(q1s[q1s.gtype == "B"]["cum_time_h"].sum()), 3),
        cum_h_C=round(float(q1s[q1s.gtype == "C"]["cum_time_h"].sum()), 3),
        n_energy_binding=int((q1a["binding"] == "能量").sum()),
    )
    out["totals"] = tot
    with open(RES / "q1_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(json.dumps(tot, ensure_ascii=False, indent=1))
    print("\n各服务区-机型最大安全载荷（前 12 行）")
    print(q1a.head(12).to_string(index=False))
    print("\n各服务区最优机型组批")
    print(best[["sid", "gtype", "n_trips", "total_mass", "total_energy", "cum_time_h"]].to_string(index=False))


if __name__ == "__main__":
    main()
