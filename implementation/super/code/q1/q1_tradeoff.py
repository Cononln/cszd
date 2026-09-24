# -*- coding: utf-8 -*-
"""问题一（3）：架次数-能耗-作业时间的精确 Pareto 权衡分析。

对每个 (服务区, 机型) 组合，求解
    E*(k) = min 总能耗  s.t.  恰好使用 k 个架次
得到精确 Pareto 前沿（架次数 k 与总能耗 E 的权衡曲线）。
由于单服务区单机型下"累计作业时间"是架次数的仿射函数，
作业时间与架次数同向变化，故三目标的实质冲突只在 (架次数, 能耗) 之间。

在此基础上给出"按架次数优先 / 按能耗优先 / 折中"三类全局方案。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import RES
from common.data import load_nodes, load_boxes, load_transport_types, sid_list
from q1.q1_solve import (GTS, BOXES, SIDS, V_SCALE, E_SCALE, max_safe_payload,
                         trip_energy, trip_energy_table, round_trip_legs)

NODES = load_nodes().set_index("id")


def min_energy_with_k(sid, g, k, qmax, Etab, masses, vols, time_limit=60):
    """恰好 k 个架次下的最小总能耗 MILP。"""
    gt = GTS[g]
    n = len(masses)
    Qcap_i = int(np.floor(qmax + 1e-9))
    Vcap_i = int(np.floor(gt["V"] * V_SCALE + 1e-9))
    m_i = [int(round(m)) for m in masses]
    v_i = [int(round(v * V_SCALE)) for v in vols]
    model = cp_model.CpModel()
    x = {(b, t): model.NewBoolVar(f"x{b}_{t}") for b in range(n) for t in range(k)}
    y = [model.NewBoolVar(f"y{t}") for t in range(k)]
    qv = [model.NewIntVar(0, Qcap_i, f"q{t}") for t in range(k)]
    ev = [model.NewIntVar(0, int(Etab.max() * E_SCALE) + 10, f"e{t}") for t in range(k)]
    for b in range(n):
        model.AddExactlyOne(x[b, t] for t in range(k))
    for t in range(k):
        model.Add(sum(m_i[b] * x[b, t] for b in range(n)) <= Qcap_i * y[t])
        model.Add(qv[t] == sum(m_i[b] * x[b, t] for b in range(n)))
        model.Add(sum(v_i[b] * x[b, t] for b in range(n)) <= Vcap_i * y[t])
        model.AddElement(qv[t], [int(round(v * E_SCALE)) for v in Etab], ev[t])
    for t in range(k - 1):
        model.Add(y[t] >= y[t + 1])
    model.Add(sum(y) == k)
    model.Minimize(sum(ev))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = 8
    st = s.Solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None
    trips = [[b for b in range(n) if s.Value(x[b, t]) == 1] for t in range(k)]
    loads = [sum(masses[b] for b in tr) for tr in trips]
    E = sum(trip_energy(g, sid, q) for q in loads)
    return E, loads


def main():
    rt_geom = {}
    for sid in SIDS:
        l1, l2 = round_trip_legs(sid)
        rt_geom[sid] = (l1.d, l1.zmax)

    rows, fronts = [], {}
    for sid in SIDS:
        sub = BOXES[BOXES["sid"] == sid]
        masses = sub["mass"].tolist()
        vols = sub["vol"].tolist()
        for g in ["A", "B", "C"]:
            gt = GTS[g]
            qmax, lim, _ = max_safe_payload(g, sid)
            if qmax < max(masses) - 1e-9:
                continue
            Etab = trip_energy_table(g, sid, int(np.floor(min(qmax, gt["Q"]))))
            # 架次数下界：质量下界与体积下界取大
            k_lo = max(int(np.ceil(sum(masses) / qmax - 1e-9)),
                       int(np.ceil(sum(vols) / gt["V"] - 1e-9)), 1)
            l1, l2 = round_trip_legs(sid)
            t_fly = l1.time(gt) + l2.time(gt)
            front = []
            for k in range(k_lo, len(masses) + 1):
                E, loads = min_energy_with_k(sid, g, k, qmax, Etab, masses, vols)
                if E is None:
                    continue
                T = (k * (gt["t_prep"] + t_fly + gt["t_hand_base"]) +
                     len(masses) * (gt["t_box_load"] + gt["t_hand_box"]))
                front.append(dict(sid=sid, gtype=g, k=k, energy=round(E, 5),
                                  cum_time_h=round(T / 3600, 4),
                                  max_load=round(max(loads), 2),
                                  min_load=round(min(loads), 2),
                                  load_std=round(float(np.std(loads)), 3)))
                if E <= 1e-9 and k > k_lo:
                    break
            fronts[f"{sid}-{g}"] = front
            rows.extend(front)

    df = pd.DataFrame(rows)
    df.to_csv(RES / "q1_pareto_fronts.csv", index=False, encoding="utf-8-sig")

    # ---------------- 全局方案：在每个服务区上选 (机型, 架次数)
    # 方案 A：架次数优先（各服务区取最少架次方案，再在其中取能耗最小）
    # 方案 B：能耗优先（各服务区取能耗最小的可行方案）
    # 方案 C：加权折中（对架次数与归一化能耗加权求和）
    def pick(rule):
        sel = []
        for sid in SIDS:
            cand = [r for r in rows if r["sid"] == sid]
            if not cand:
                continue
            sel.append(rule(cand))
        return pd.DataFrame(sel)

    def agg(sel):
        return dict(n_trips=int(sel["k"].sum()),
                    energy=round(float(sel["energy"].sum()), 4),
                    cum_time_h=round(float(sel["cum_time_h"].sum()), 3))

    schemes = {}
    schemes["架次优先"] = agg(pick(lambda c: min(c, key=lambda r: (r["k"], r["energy"]))))
    schemes["能耗优先"] = agg(pick(lambda c: min(c, key=lambda r: (r["energy"], r["k"]))))
    for w in [0.1, 0.3, 0.5, 0.7, 0.9]:
        e_scale = max(r["energy"] for r in rows)
        k_scale = max(r["k"] for r in rows)
        schemes[f"加权w={w}"] = agg(pick(
            lambda c: min(c, key=lambda r: w * r["k"] / k_scale +
                                             (1 - w) * r["energy"] / e_scale)))

    # 精选三个代表方案写入结果
    picks = {}
    picks["最少架次"] = pick(lambda c: min(c, key=lambda r: (r["k"], r["energy"])))
    picks["最低能耗"] = pick(lambda c: min(c, key=lambda r: (r["energy"], r["k"])))
    e_scale = max(r["energy"] for r in rows)
    k_scale = max(r["k"] for r in rows)
    picks["均衡方案"] = pick(lambda c: min(
        c, key=lambda r: 0.5 * r["k"] / k_scale + 0.5 * r["energy"] / e_scale))

    with open(RES / "q1_tradeoff.json", "w", encoding="utf-8") as f:
        json.dump(dict(schemes=schemes,
                       picks={k: v.to_dict("records") for k, v in picks.items()}),
                  f, ensure_ascii=False, indent=1)

    print("=== 全局方案对比（15 个服务区汇总） ===")
    for k, v in schemes.items():
        print(f"{k:>10s}: 架次 {v['n_trips']:3d}  能耗 {v['energy']:8.3f} kWh  "
              f"累计作业 {v['cum_time_h']:7.3f} h")

    print("\n=== 典型服务区 Pareto 前沿（架次数 vs 能耗） ===")
    for key in ["S001-C", "S002-C", "S009-B"]:
        f = fronts.get(key, [])
        print(f"-- {key}")
        for r in f:
            print(f"   k={r['k']}  E={r['energy']:.4f} kWh  负载[{r['min_load']},{r['max_load']}]  "
                  f"标准差 {r['load_std']:.2f}  作业 {r['cum_time_h']:.3f} h")


if __name__ == "__main__":
    main()
