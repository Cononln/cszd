# -*- coding: utf-8 -*-
"""问题二核心模型：架次构造、快速评估、贪心调度、CP-SAT 精确调度。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.data import (load_boxes, load_nodes, load_transport_types,
                         load_transport_fleet, load_transport_batteries, sid_list)
from common.route import (GTS, NODES, SIDS, leg_energy, leg_time, trip_metrics,
                          tsp_order)

BOXES = load_boxes()
FLEET = load_transport_fleet()
BATT = load_transport_batteries()
NR_BATT = {g: BATT[g]["n"] for g in BATT}
T_FULL = {g: BATT[g]["t_full"] for g in BATT}

BOX_IDX = {b: i for i, b in enumerate(BOXES["box"])}
G_OF_DRONE = dict(zip(FLEET["uid"], FLEET["gtype"]))
DRONES_OF = {g: [u for u, gg in G_OF_DRONE.items() if gg == g] for g in "ABC"}

# ---- 供 ALNS 内层循环使用的扁平数组（避免 pandas 开销）
_N = len(BOXES)
B_MASS = BOXES["mass"].to_numpy(float)
B_VOL = BOXES["vol"].to_numpy(float)
B_PRIO = BOXES["prio"].to_numpy(float)
B_SID = BOXES["sid"].to_numpy()
B_TEXP = np.nan_to_num(BOXES["t_exp"].to_numpy(float), nan=1e9)
B_FIRST = BOXES["first"].to_numpy(bool)
B_TFIRST = np.nan_to_num(BOXES["t_first"].to_numpy(float), nan=1e9)
_SID_LIST = sid_list()
SID_IDX = {s: i for i, s in enumerate(_SID_LIST)}

# 每个服务区每种物资的单箱质量/体积（同名物资参数一致，取首箱即可）
COMM = list(dict.fromkeys(BOXES["type"].tolist()))
COMM_IDX = {c: i for i, c in enumerate(COMM)}
CMASS = np.array([BOXES[BOXES["type"] == c]["mass"].iloc[0] for c in COMM])
CVOL = np.array([BOXES[BOXES["type"] == c]["vol"].iloc[0] for c in COMM])


# ==================================================================== 充电
def charge_time(g, soc):
    s = float(np.clip(soc, 0.0, 1.0))
    Tf = T_FULL[g]
    if s < 0.90:
        return Tf * (0.65 * (0.90 - s) / 0.90 + 0.35)
    return Tf * 0.35 * (1.0 - s) / 0.10


# ==================================================================== 架次
class Trip:
    """一个运输架次：机型 g、按序访问的服务区、逐箱货箱清单。"""

    __slots__ = ("gtype", "stops", "box_ids", "mass_by_stop", "nbox_by_stop",
                 "vol_by_stop", "metrics", "offset", "dur", "soc_end", "charge_s",
                 "arr_off", "arr_texp", "arr_prio", "arr_first", "arr_tfirst",
                 "arr_mass", "arr_sididx", "sum_vol", "sum_mass", "feasible_flag")

    def __init__(self, gtype, box_ids, order=None):
        if len(box_ids) == 0:
            raise ValueError("空架次")
        self.gtype = gtype
        self.box_ids = list(box_ids)
        if len(set(self.box_ids)) != len(self.box_ids):
            raise ValueError(f"架次内货箱重复：{sorted(self.box_ids)}")
        bidx = np.array([BOX_IDX[b] for b in self.box_ids], dtype=int)
        sids = B_SID[bidx]
        mass = B_MASS[bidx]
        vol = B_VOL[bidx]
        # 纯 numpy 聚合，避免 pandas 开销（ALNS 内层高频构造）
        mbs, nbs, vbs = {}, {}, {}
        for k, s in enumerate(sids):
            mbs[s] = mbs.get(s, 0.0) + float(mass[k])
            nbs[s] = nbs.get(s, 0) + 1
            vbs[s] = vbs.get(s, 0.0) + float(vol[k])
        self.mass_by_stop, self.nbox_by_stop, self.vol_by_stop = mbs, nbs, vbs
        stops = sorted(mbs.keys())
        self.stops = list(order) if order else list(tsp_order(gtype, tuple(stops)))
        self.metrics = trip_metrics(gtype, self.stops, self.mass_by_stop,
                                    self.nbox_by_stop)
        self.dur = self.metrics["total_t"]
        # 各站"交付完成"相对架次开始的偏移
        gt = GTS[gtype]
        off = gt["t_prep"] + len(box_ids) * gt["t_box_load"]
        acc = {}
        fly = 0.0
        for k, s in enumerate(self.stops):
            a = "O01" if k == 0 else self.stops[k - 1]
            fly += leg_time(gtype, a, s, gt)
            off += fly if k == 0 else 0.0
            # 到达 s 的时刻（相对架次开始）
            arrive = gt["t_prep"] + len(box_ids) * gt["t_box_load"] + sum(
                leg_time(gtype, ("O01" if m == 0 else self.stops[m - 1]), self.stops[m], gt)
                for m in range(k + 1))
            hand = gt["t_hand_base"] + self.nbox_by_stop.get(s, 0) * gt["t_hand_box"]
            acc[s] = arrive + hand
        self.offset = acc
        self.soc_end = self.metrics["soc_end"]
        self.charge_s = charge_time(gtype, self.soc_end)
        # ---- 扁平数组（ALNS 内层快速评估）
        self.arr_off = np.array([acc[B_SID[i]] for i in bidx], dtype=float)
        self.arr_texp = B_TEXP[bidx]
        self.arr_prio = B_PRIO[bidx]
        self.arr_first = B_FIRST[bidx]
        self.arr_tfirst = B_TFIRST[bidx]
        self.arr_mass = mass
        self.arr_sididx = np.array([SID_IDX[B_SID[i]] for i in bidx], dtype=int)
        self.sum_mass = float(mass.sum())
        self.sum_vol = float(vol.sum())
        self.feasible_flag = (self.metrics["feasible"]
                              and self.sum_mass <= GTS[gtype]["Q"] + 1e-9
                              and self.sum_vol <= GTS[gtype]["V"] + 1e-9)

    # ------------------------------------------------------------ 快速指标
    def lateness(self, start):
        """返回 (加权延误, 首批最大超时, 延误箱数)。"""
        lat = np.clip(start + self.arr_off - self.arr_texp, 0.0, None)
        w = float((lat * self.arr_prio).sum()) if lat.size else 0.0
        if self.arr_first.any():
            fv = float(np.max(start + self.arr_off[self.arr_first]
                              - self.arr_tfirst[self.arr_first]))
            fv = max(fv, 0.0)
        else:
            fv = 0.0
        return w, fv, int((lat > 1e-6).sum())

    @property
    def energy(self):
        return self.metrics["energy"]

    @property
    def feasible(self):
        return self.feasible_flag

    def deadline(self):
        """本架次要求的最早首批截止时间（无首批箱则为 None）。"""
        sub = BOXES[BOXES["box"].isin(self.box_ids)]
        sub = sub[sub["first"]]
        if sub.empty:
            return None
        return float(sub["t_first"].min())

    def first_violation(self, start):
        """在 start 时刻起飞时，首批箱的最大超时量 (s)；无违反为 0。"""
        if not self.arr_first.any():
            return 0.0
        return max(float(np.max(start + self.arr_off[self.arr_first]
                                - self.arr_tfirst[self.arr_first])), 0.0)


def clone_with(trip, box_ids=None, order=None, gtype=None):
    return Trip(gtype or trip.gtype, box_ids or trip.box_ids, order)


# ==================================================================== 评估
def solution_metrics(trips, sched, boxes_df=None):
    """汇总方案指标。sched: list of dict(trip_idx, drone, battery, start, end)."""
    boxes_df = BOXES if boxes_df is None else boxes_df
    n_trip = len(trips)
    energy = sum(t.energy for t in trips)
    makespan = max((s["end"] for s in sched), default=0.0)
    doc = {}      # 逐箱交付时刻
    for i, s in enumerate(sched):
        t = trips[s["trip_idx"]]
        for bx in t.box_ids:
            doc[bx] = s["start"] + t.offset[BOXES.set_index("box").loc[bx, "sid"]]
    sub = boxes_df.copy()
    sub["deliver"] = sub["box"].map(doc)
    lat = (sub["deliver"] - sub["t_exp"]).clip(lower=0).fillna(0.0)
    prio_lat = float((lat * sub["prio"]).sum())
    late_cnt = int((lat > 1e-6).sum())
    first_viol = 0.0
    for i, s in enumerate(sched):
        first_viol = max(first_viol, trips[s["trip_idx"]].first_violation(s["start"]))
    return dict(n_trips=n_trip, energy=energy, makespan=makespan,
                prio_lateness=prio_lat, late_boxes=late_cnt,
                first_violation=first_viol,
                mean_deliver=float(sub["deliver"].mean()),
                on_time_rate=float((lat <= 1e-6).mean()),
                doc=doc, deliver_df=sub)


# ==================================================================== 快速评估
def eval_fast(trips, sched):
    """轻量指标汇总（无 pandas），供 ALNS 内层循环高频调用。"""
    mk = 0.0
    late_w = 0.0
    late_n = 0
    fv = 0.0
    energy = 0.0
    for tr in trips:
        energy += tr.energy
    for s in sched:
        t = trips[s["trip_idx"]]
        if s["end"] > mk:
            mk = s["end"]
        w, f, n = t.lateness(s["start"])
        late_w += w
        late_n += n
        if f > fv:
            fv = f
    return dict(n_trips=len(trips), energy=energy, makespan=mk,
                prio_lateness=late_w, late_boxes=late_n, first_violation=fv)


def greedy_schedule_fast(trips, horizon=1e9, deadline_aware=True):
    """快速列表调度（纯 Python 循环，无 pandas）。"""
    if not trips:
        return [], dict(n_trips=0, energy=0.0, makespan=0.0, prio_lateness=0.0,
                        late_boxes=0, first_violation=0.0)
    if deadline_aware:
        order = sorted(range(len(trips)),
                       key=lambda i: (float(trips[i].arr_tfirst.min())
                                      if trips[i].arr_first.any() else 1e12,
                                      -trips[i].energy))
    else:
        order = list(range(len(trips)))
    drone_free = {u: 0.0 for u in G_OF_DRONE}
    batt_free = {(g, b): 0.0 for g in "ABC" for b in range(NR_BATT[g])}
    sched = []
    for i in order:
        t = trips[i]
        g = t.gtype
        best_key = None
        best = None
        for u in DRONES_OF[g]:
            du = drone_free[u]
            for b in range(NR_BATT[g]):
                st = du if du > batt_free[(g, b)] else batt_free[(g, b)]
                end = st + t.dur
                if end > horizon:
                    continue
                viol = t.first_violation(st)
                key = (1 if viol > 1e-6 else 0, end)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (st, u, b)
        if best is None:
            g_drones = DRONES_OF[g]
            u = min(g_drones, key=lambda x: drone_free[x])
            b = min(range(NR_BATT[g]), key=lambda x: batt_free[(g, x)])
            st = max(drone_free[u], batt_free[(g, b)])
            best = (st, u, b)
        st, u, b = best
        end = st + t.dur
        sched.append(dict(trip_idx=i, drone=u, battery=f"{g}{b+1}",
                          batt_key=(g, b), start=st, end=end))
        drone_free[u] = end
        batt_free[(g, b)] = end + t.charge_s
    return sched, eval_fast(trips, sched)


def objective(met, ref, w, big=1e4):
    """归一化加权目标（越小越好）。ref 为各指标参考量级。"""
    return (w["late"] * met["prio_lateness"] / ref["late"]
            + w["mk"] * met["makespan"] / ref["mk"]
            + w["e"] * met["energy"] / ref["e"]
            + w["n"] * met["n_trips"] / ref["n"]
            + big * met["first_violation"] / 3600.0)


# ==================================================================== 贪心调度
def greedy_schedule(trips, horizon=1e9):
    """列表调度：按紧迫度排序，为每个架次选使完工最早的（无人机, 电池）组合。

    返回 (sched, metrics)。用于 ALNS 中大量快速评估。
    """
    order = sorted(range(len(trips)),
                   key=lambda i: (trips[i].deadline() if trips[i].deadline() is not None
                                  else 1e12, -trips[i].energy))
    drone_free = {u: 0.0 for u in G_OF_DRONE}
    batt_free = {(g, b): 0.0 for g in "ABC" for b in range(NR_BATT[g])}
    sched = []
    for i in order:
        t = trips[i]
        g = t.gtype
        best = None
        for u in DRONES_OF[g]:
            for b in range(NR_BATT[g]):
                st = max(drone_free[u], batt_free[(g, b)])
                if st + t.dur > horizon:
                    continue
                viol = t.first_violation(st)
                key = (viol > 1e-6, st + t.dur)
                if best is None or key < best[0]:
                    best = (key, st, u, b)
        if best is None:                       # 兜底：最空闲资源
            u = min(DRONES_OF[g], key=lambda x: drone_free[x])
            b = min(range(NR_BATT[g]), key=lambda x: batt_free[(g, x)])
            st = max(drone_free[u], batt_free[(g, b)])
            best = ((True, st + t.dur), st, u, b)
        _, st, u, b = best
        end = st + t.dur
        sched.append(dict(trip_idx=i, drone=u, battery=f"{g}{b+1}",
                          batt_key=(g, b), start=st, end=end))
        drone_free[u] = end
        batt_free[(g, b)] = end + t.charge_s
    return sched, solution_metrics(trips, sched)


# ==================================================================== CP-SAT 调度
def cp_schedule(trips, w_makespan=1.0, w_late=1.0, time_limit=90.0, horizon=28800,
                verbosity=False):
    """精确调度：无人机/电池指派 + 时序 + 首批硬时限 + 加权延误最小化。"""
    n = len(trips)
    if n == 0:
        return [], None, "EMPTY"
    m = cp_model.CpModel()
    H = int(horizon)
    start = [m.NewIntVar(0, H, f"s{i}") for i in range(n)]
    # 向上取整：区间长度只会偏长，保证整数时刻解在连续时间口径下依然可行
    dur = [int(np.ceil(t.dur - 1e-9)) for t in trips]
    chg = [int(np.ceil(t.charge_s - 1e-9)) for t in trips]

    # 无人机指派
    d_lit = {}
    for i, t in enumerate(trips):
        lits = []
        for u in DRONES_OF[t.gtype]:
            lv = m.NewBoolVar(f"d{i}_{u}")
            d_lit[(i, u)] = lv
            lits.append(lv)
        m.AddExactlyOne(lits)
    # 电池指派
    b_lit = {}
    for i, t in enumerate(trips):
        lits = []
        for b in range(NR_BATT[t.gtype]):
            lv = m.NewBoolVar(f"b{i}_{b}")
            b_lit[(i, b)] = lv
            lits.append(lv)
        m.AddExactlyOne(lits)

    # 无人机上的可选区间 + NoOverlap
    for u in G_OF_DRONE:
        ivs = []
        for i, t in enumerate(trips):
            if (i, u) not in d_lit:
                continue
            ivs.append(m.NewOptionalFixedSizeIntervalVar(
                start[i], dur[i], d_lit[(i, u)], f"iv_d{i}_{u}"))
        if ivs:
            m.AddNoOverlap(ivs)

    # 电池：占用 = 任务时长 + 充电时长
    for g in "ABC":
        for b in range(NR_BATT[g]):
            ivs = []
            for i, t in enumerate(trips):
                if t.gtype != g:
                    continue
                ivs.append(m.NewOptionalFixedSizeIntervalVar(
                    start[i], dur[i] + chg[i], b_lit[(i, b)], f"iv_b{i}_{b}"))
            if ivs:
                m.AddNoOverlap(ivs)

    # 首批硬时限
    hard_infeasible = []
    for i, t in enumerate(trips):
        sub = BOXES[BOXES["box"].isin(t.box_ids) & BOXES["first"]]
        for r in sub.itertuples():
            latest = int(np.floor(r.t_first - t.offset[r.sid]))
            if latest < 0:
                hard_infeasible.append((t, r.box))
                latest = 0
            m.Add(start[i] <= latest)

    # 完工时间
    ends = [start[i] + dur[i] for i in range(n)]
    mk = m.NewIntVar(0, H + 1000, "makespan")
    m.AddMaxEquality(mk, ends)

    # 软性延误（加权应急优先系数）
    late_terms = []
    for i, t in enumerate(trips):
        sub = BOXES[BOXES["box"].isin(t.box_ids)]
        for r in sub.itertuples():
            off = int(round(t.offset[r.sid]))
            exp = int(round(r.t_exp))
            lv = m.NewIntVar(0, H, f"lt{i}_{r.Index}")
            m.AddMaxEquality(lv, [start[i] + off - exp, 0])
            late_terms.append(int(round(r.prio)) * lv)

    # 线性加权目标（CP-SAT 目标须为线性表达式）
    obj = int(round(w_makespan * 100)) * mk
    if late_terms:
        obj += int(round(w_late * 100 / max(n, 1))) * sum(late_terms)
    m.Minimize(obj)

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = 8
    if verbosity:
        s.parameters.log_search_progress = True
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, s.StatusName(st)
    sched = []
    for i, t in enumerate(trips):
        u = next(u for u in DRONES_OF[t.gtype] if s.Value(d_lit[(i, u)]))
        b = next(b for b in range(NR_BATT[t.gtype]) if s.Value(b_lit[(i, b)]))
        sched.append(dict(trip_idx=i, drone=u, battery=f"{t.gtype}{b+1}",
                          batt_key=(t.gtype, b),
                          start=float(s.Value(start[i])),
                          end=float(s.Value(start[i]) + dur[i])))
    sched.sort(key=lambda r: r["start"])
    return sched, solution_metrics(trips, sched), s.StatusName(st)


# ==================================================================== 可行性
def validate(trips, sched, check_deadlines=True):
    """逐项校验方案的资源可行性。"""
    issues = []
    gt_ok = True
    for i, t in enumerate(trips):
        gt = GTS[t.gtype]
        if t.metrics["mass"] > gt["Q"] + 1e-6:
            issues.append(f"架次{i} 载质量 {t.metrics['mass']:.2f} > {gt['Q']}")
        if sum(t.vol_by_stop.values()) > gt["V"] + 1e-9:
            issues.append(f"架次{i} 装载体积超限")
        if not t.metrics["feasible"]:
            issues.append(f"架次{i} 返航安全余量不足 (E={t.energy:.3f})")
        if sum(1 for s in sched if s["trip_idx"] == i) != 1:
            issues.append(f"架次{i} 未被调度")
    # 无人机串行
    for u in G_OF_DRONE:
        ss = sorted([s for s in sched if s["drone"] == u], key=lambda r: r["start"])
        for a, b in zip(ss[:-1], ss[1:]):
            if b["start"] < a["end"] - 1e-6:
                issues.append(f"无人机{u} 架次重叠")
            if G_OF_DRONE[u] != trips[a["trip_idx"]].gtype:
                issues.append(f"无人机{u} 机型不匹配")
    # 电池串行（含充电）
    for key in set(s["batt_key"] for s in sched):
        ss = sorted([s for s in sched if s["batt_key"] == key], key=lambda r: r["start"])
        for a, b in zip(ss[:-1], ss[1:]):
            ta = trips[a["trip_idx"]]
            if b["start"] < a["end"] + ta.charge_s - 1e-6:
                issues.append(f"电池{key} 充电窗口冲突")
    # 覆盖性
    allb = [bx for t in trips for bx in t.box_ids]
    if len(allb) != len(set(allb)):
        issues.append("货箱重复投递")
    if set(allb) != set(BOXES["box"]):
        issues.append(f"货箱覆盖不全：缺 {len(set(BOXES['box']) - set(allb))} 箱")
    if check_deadlines:
        for i, t in enumerate(trips):
            sch = next(s for s in sched if s["trip_idx"] == i)
            v = t.first_violation(sch["start"])
            if v > 1e-6:
                issues.append(f"架次{i} 首批超时 {v:.1f}s")
    return issues
