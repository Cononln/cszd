# -*- coding: utf-8 -*-
"""问题二：异构无人机多点多架次运输调度。

两阶段求解框架
  Stage A  架次模式选择 MILP（CP-SAT）：从"服务区子集×机型"模式中选出架次结构，
           决定每个服务区各类货箱由哪类模式承运，最小化架次数与路由代价；
  Stage B  精确装箱：对每个被选中的模式，用 MILP 把货箱精确装入 z 个架次；
  Stage C  ALNS 大规模邻域搜索：在"货箱-架次"分配与"服务区访问顺序"上做
           破坏-修复 + 局部搜索，目标为配送及时性/完工时间/能耗/架次数加权；
  Stage D  CP-SAT 精确调度：无人机与共享电池指派、时序、首批硬时限。

输出：results/q2_*.csv / .json
"""
from __future__ import annotations

import json
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import RES
from common.data import (load_boxes, load_transport_types, sid_list)
from common.route import (GTS, NODES, SIDS, leg_time, precompute_all_legs,
                          trip_metrics, tsp_order)
from q2.q2_model import (B_MASS, B_VOL, B_SID, BOXES, BOX_IDX, COMM, COMM_IDX,
                         CMASS, CVOL, DRONES_OF, NR_BATT, Trip, charge_time,
                         cp_schedule, eval_fast, greedy_schedule,
                         greedy_schedule_fast, objective, solution_metrics,
                         validate)

RNG_SEED = 20260923
W_DEFAULT = dict(late=1.0, mk=0.30, e=0.30, n=0.30)


# ==================================================================== 需求
def demand_table():
    """(服务区, 物资) -> 箱数。"""
    tab = {}
    for s in SIDS:
        for c in COMM:
            n = int(((B_SID == s) & (BOXES["type"] == c).to_numpy()).sum())
            tab[(s, c)] = n
    return tab


DEMAND = demand_table()


def boxes_of(sid, comm):
    m = (B_SID == sid) & (BOXES["type"] == comm).to_numpy()
    return BOXES["box"].to_numpy()[m].tolist()


# ==================================================================== Stage A
def gen_patterns(max_size=3):
    """生成候选架次模式 (服务区子集, 机型)。"""
    pats = []
    for g in ["A", "B", "C"]:
        gt = GTS[g]
        Q, V = gt["Q"], gt["V"]
        for k in range(1, max_size + 1):
            for S in combinations(SIDS, k):
                mass = sum(DEMAND[(s, c)] * CMASS[COMM_IDX[c]]
                           for s in S for c in COMM)
                vol = sum(DEMAND[(s, c)] * CVOL[COMM_IDX[c]]
                          for s in S for c in COMM)
                if mass <= 1e-9:
                    continue
                # 至少需要几个架次（容量下界）
                zmin = max(int(np.ceil(mass / Q - 1e-9)),
                           int(np.ceil(vol / V - 1e-9)), 1)
                if zmin > max_size:          # 一个模式最多 3 个架次
                    continue
                # 单箱可行性
                if max(CMASS) > Q:
                    continue
                order = tsp_order(g, tuple(sorted(S)))
                seq = ["O01"] + list(order) + ["O01"]
                T = sum(leg_time(g, a, b) for a, b in zip(seq[:-1], seq[1:]))
                pats.append(dict(S=tuple(sorted(S)), g=g, zmin=zmin,
                                 mass=mass, vol=vol, order=order, T=T, Q=Q, V=V))
    return pats


def stage_a_milp(pats, w_trip=1.0, w_time=0.15, w_energy=0.15, time_limit=180):
    """架次模式选择 MILP。返回 (选中的模式及货箱分配, 状态)。"""
    m = cp_model.CpModel()
    n_p = len(pats)
    T_ref = max(p["T"] for p in pats)
    # 各模式的单位架次时间/能耗代理
    times = [p["T"] for p in pats]
    # 变量
    n = [m.NewIntVar(0, 3, f"n{k}") for k in range(n_p)]
    y = {}
    for k, p in enumerate(pats):
        for s in p["S"]:
            for c in COMM:
                nn = DEMAND[(s, c)]
                if nn > 0:
                    y[(k, s, c)] = m.NewIntVar(0, nn, f"y{k}_{s}_{c}")
    # 需求覆盖
    for s in SIDS:
        for c in COMM:
            nn = DEMAND[(s, c)]
            if nn == 0:
                continue
            terms = [y[(k, s, c)] for k, p in enumerate(pats)
                     if s in p["S"] and (k, s, c) in y]
            if not terms:
                return None, "NO_COVER"
            m.Add(sum(terms) == nn)
    # 容量
    for k, p in enumerate(pats):
        mt = sum(y[(k, s, c)] * int(round(CMASS[COMM_IDX[c]] * 100))
                 for s in p["S"] for c in COMM if (k, s, c) in y)
        vt = sum(y[(k, s, c)] * int(round(CVOL[COMM_IDX[c]] * 100000))
                 for s in p["S"] for c in COMM if (k, s, c) in y)
        m.Add(mt <= int(round(p["Q"] * 100)) * n[k])
        m.Add(vt <= int(round(p["V"] * 100000)) * n[k])
        # 启用模式才可分配货箱
        for s in p["S"]:
            for c in COMM:
                if (k, s, c) in y:
                    m.Add(y[(k, s, c)] <= DEMAND[(s, c)] * n[k])
    m.Minimize(int(round(w_trip * 1000)) * sum(n)
               + int(round(w_time * 300)) * sum(
                   int(round(times[k] / T_ref * 1000)) * n[k] for k in range(n_p)))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_search_workers = 8
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, s.StatusName(st)
    chosen = []
    for k, p in enumerate(pats):
        z = s.Value(n[k])
        if z <= 0:
            continue
        alloc = {(sid, c): s.Value(y[(k, sid, c)])
                 for sid in p["S"] for c in COMM if (k, sid, c) in y}
        chosen.append(dict(pat=p, z=z, alloc=alloc))
    # 目标值换算：只保留真正使用的模式
    return chosen, s.StatusName(st)


def pack_pattern(chosen, time_limit=20):
    """把每个模式的货箱精确装入 z 个架次（2 维装箱 MILP）。

    注意：同一 (服务区,物资) 的货箱可能被多个模式瓜分，必须用全局游标分配
    具体箱号，否则会出现同一货箱被重复投递。
    """
    trips = []
    cursor = {}
    for item in chosen:
        p, z = item["pat"], item["z"]
        g = p["g"]
        gt = GTS[g]
        ids = []
        for (sid, c), cnt in sorted(item["alloc"].items()):
            if cnt <= 0:
                continue
            start = cursor.get((sid, c), 0)
            ids.extend(boxes_of(sid, c)[start:start + cnt])
            cursor[(sid, c)] = start + cnt
        if not ids:
            continue
        mass = np.array([B_MASS[BOX_IDX[b]] for b in ids])
        vol = np.array([B_VOL[BOX_IDX[b]] for b in ids])
        m = cp_model.CpModel()
        K = z
        x = {(i, k): m.NewBoolVar(f"x{i}_{k}") for i in range(len(ids)) for k in range(K)}
        for i in range(len(ids)):
            m.AddExactlyOne(x[i, k] for k in range(K))
        for k in range(K):
            m.Add(sum(int(round(mass[i] * 100)) * x[i, k] for i in range(len(ids)))
                  <= int(round(gt["Q"] * 100)))
            m.Add(sum(int(round(vol[i] * 100000)) * x[i, k] for i in range(len(ids)))
                  <= int(round(gt["V"] * 100000)))
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = time_limit
        s.parameters.num_search_workers = 4
        st = s.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # 退化为单箱单架次
            for b in ids:
                trips.append(Trip(g, [b]))
            continue
        groups = [[] for _ in range(K)]
        for i, b in enumerate(ids):
            for k in range(K):
                if s.Value(x[i, k]):
                    groups[k].append(b)
        for grp in groups:
            if grp:
                trips.append(Trip(g, grp))
    return trips


# ==================================================================== ALNS
def repair_insert(trips, pool, rng, allow_new=True):
    """把 pool 中的货箱依次插入现有架次或新建架次（贪心-最优位置）。"""
    for b in pool:
        best = None
        for i, t in enumerate(trips):
            cand_ids = t.box_ids + [b]
            nt = Trip(t.gtype, cand_ids)
            if not nt.feasible:
                continue
            # 代价增量：能耗 + 时长
            d = (nt.energy - t.energy) * 1.0 + (nt.dur - t.dur) / 1000.0
            if best is None or d < best[0]:
                best = (d, i, nt)
        if best is not None:
            trips[best[1]] = best[2]
        elif allow_new:
            for g in ["A", "B", "C"]:
                nt = Trip(g, [b])
                if nt.feasible:
                    trips.append(nt)
                    break
            else:
                return False
    return True


def pack_ffd(ids, g):
    """给定货箱编号列表，按首次适应递减(FFD)装入机型 g 的若干架次。"""
    gt = GTS[g]
    idxs = np.array([BOX_IDX[b] for b in ids], dtype=int)
    order = idxs[np.argsort(-B_MASS[idxs], kind="stable")]
    bins = []
    for i in order:
        m, v = float(B_MASS[i]), float(B_VOL[i])
        placed = False
        for b in bins:
            if b[0] + m <= gt["Q"] + 1e-9 and b[1] + v <= gt["V"] + 1e-9:
                b[0] += m
                b[1] += v
                b[2].append(BOXES["box"].iloc[i])
                placed = True
                break
        if not placed:
            bins.append([m, v, [BOXES["box"].iloc[i]]])
    return [Trip(g, b[2]) for b in bins]


def pack_area_best(sid, ids=None):
    """某服务区货箱的最优机型 FFD 组批（架次数优先，能耗次之）。"""
    if ids is None:
        ids = BOXES["box"].to_numpy()[B_SID == sid].tolist()
    best, best_key = None, None
    for g in ["C", "B", "A"]:
        ts = pack_ffd(ids, g)
        if not ts or not all(t.feasible for t in ts):
            continue
        key = (len(ts), sum(t.energy for t in ts))
        if best_key is None or key < best_key:
            best, best_key = ts, key
    return best if best else pack_ffd(ids, "C")


def tight_sids(threshold=3600.0):
    out = []
    for s in SIDS:
        m = (B_SID == s) & BOXES["first"].to_numpy()
        if m.any() and float(BOXES.loc[m, "t_first"].min()) <= threshold:
            out.append(s)
    return out


def construct_initial(seed=RNG_SEED):
    """机队感知的两波构造启发式。

    第一波：对首批截止最紧（<=3600 s）的各服务区各建一个早班架次，只装本站
            货箱，并**按机队规模（4A/2B/2C）分配机型**，保证 8 个早班架次能
            在第 0 秒同时起飞；
    第二波：其余货箱按服务区 FFD 组批；
    收尾  ：贪心合并相邻服务区架次。
    """
    trips, used = [], set()
    tight = tight_sids()
    # 工作量大的紧服务区优先占用载重更大的机型
    tight_sorted = sorted(tight, key=lambda s: -float(
        BOXES.loc[B_SID == s, "mass"].sum()))
    plan = ["C", "C", "B", "B", "A", "A", "A", "A"]
    for k, s in enumerate(tight_sorted):
        g = plan[k] if k < len(plan) else "A"
        fids = BOXES["box"].to_numpy()[(B_SID == s) & BOXES["first"].to_numpy()].tolist()
        t = Trip(g, fids)
        if not (t.feasible and t.first_violation(0.0) <= 1e-6):
            for gg in ["C", "B", "A"]:
                c = Trip(gg, fids)
                if c.feasible and c.first_violation(0.0) <= 1e-6:
                    t, g = c, gg
                    break
        # 同站非首批箱：在不破坏首批时限的前提下尽量搭载
        others = BOXES["box"].to_numpy()[
            (B_SID == s) & (~BOXES["first"].to_numpy())].tolist()
        others.sort(key=lambda b: -B_MASS[BOX_IDX[b]])
        for b in others:
            nt = Trip(g, t.box_ids + [b])
            if nt.feasible and nt.first_violation(0.0) <= 1e-6:
                t = nt
        trips.append(t)
        used |= set(t.box_ids)

    # 第二波：其余货箱按服务区组批
    rest = [b for b in BOXES["box"].to_numpy() if b not in used]
    by_sid = {}
    for b in rest:
        by_sid.setdefault(B_SID[BOX_IDX[b]], []).append(b)
    for s, ids in by_sid.items():
        trips.extend(pack_area_best(s, ids))

    return try_merge_all(trips, protect_deadlines=True)


def try_merge_all(trips, protect_deadlines=False):
    """贪心合并：反复尝试把两两架次合并为一个更省的架次，直到无法改进。

    protect_deadlines=True 时，合并必须不使"首批超时"变差——合并会把货箱
    集中到更少的无人机上，若机队规模有限（A 4 架 / B 2 架 / C 2 架），
    过度合并会让紧时限服务区的架次排队，反而破坏首批时限。
    """
    def fv_of(ts):
        return greedy_schedule_fast(ts)[1]["first_violation"]

    cur_fv = fv_of(trips) if protect_deadlines else 0.0
    improved = True
    while improved and len(trips) > 1:
        improved = False
        trips = sorted(trips, key=lambda t: -t.energy)
        for i in range(len(trips)):
            for j in range(i + 1, len(trips)):
                a, b = trips[i], trips[j]
                cand = None
                best_key = None
                for g in {a.gtype, b.gtype, "C"}:
                    nt = Trip(g, a.box_ids + b.box_ids)
                    if not nt.feasible:
                        continue
                    key = nt.energy
                    if best_key is None or key < best_key:
                        cand, best_key = nt, key
                if cand is None:
                    continue
                old = a.energy + b.energy
                if best_key >= old - 1e-9:
                    continue
                new = [t for k, t in enumerate(trips) if k not in (i, j)] + [cand]
                if protect_deadlines:
                    nfv = fv_of(new)
                    if nfv > cur_fv + 1e-9:
                        continue
                    cur_fv = nfv
                trips = new
                improved = True
                break
            if improved:
                break
    return trips


def alns(trips0, ref, w, iters=15000, seed=RNG_SEED, time_limit=240.0,
         verbose=False):
    """大规模邻域搜索：破坏-修复 + 局部移动 + 模拟退火接受准则。"""
    rng = np.random.default_rng(seed)
    t0 = time.time()

    def evaluate(ts):
        sched, met = greedy_schedule_fast(ts)
        return objective(met, ref, w), met, sched

    cur = [Trip(t.gtype, list(t.box_ids), list(t.stops)) for t in trips0]
    cur_obj, cur_met, cur_sched = evaluate(cur)
    best, best_obj, best_met, best_sched = cur, cur_obj, cur_met, cur_sched
    hist = [(0, cur_obj, cur_met["n_trips"], cur_met["energy"],
             cur_met["makespan"], cur_met["prio_lateness"], cur_met["first_violation"])]
    T = max(0.02 * cur_obj, 1e-6)
    cool = (0.001 / 1.0) ** (1.0 / max(iters, 1))

    for it in range(1, iters + 1):
        if time.time() - t0 > time_limit:
            break
        cand = [Trip(t.gtype, list(t.box_ids), list(t.stops)) for t in cur]
        op = rng.integers(0, 6)
        ok = True

        if op == 0 and len(cand) >= 2:
            # 破坏-修复：移除若干架次后重插全部货箱
            k = int(rng.integers(1, min(4, len(cand)) + 1))
            idx = rng.choice(len(cand), size=k, replace=False)
            pool = []
            for i in sorted(idx, reverse=True):
                pool.extend(cand.pop(i).box_ids)
            rng.shuffle(pool)
            ok = repair_insert(cand, pool, rng)
        elif op == 1 and len(cand) >= 2:
            # 迁移一个货箱到另一架次
            src = int(rng.integers(len(cand)))
            if len(cand[src].box_ids) >= 2:
                b = cand[src].box_ids[int(rng.integers(len(cand[src].box_ids)))]
                rest = [b2 for b2 in cand[src].box_ids if b2 != b]
                nt_src = Trip(cand[src].gtype, rest)
                dst = int(rng.integers(len(cand)))
                if dst != src and nt_src.feasible:
                    nt_dst = Trip(cand[dst].gtype, cand[dst].box_ids + [b])
                    if nt_dst.feasible:
                        cand[src], cand[dst] = nt_src, nt_dst
                    else:
                        ok = False
                else:
                    ok = False
        elif op == 2:
            # 拆分架次
            i = int(rng.integers(len(cand)))
            if len(cand[i].box_ids) >= 2:
                ids = list(cand[i].box_ids)
                rng.shuffle(ids)
                h = len(ids) // 2
                a = Trip(cand[i].gtype, ids[:h])
                b = Trip(cand[i].gtype, ids[h:])
                if a.feasible and b.feasible:
                    cand[i] = a
                    cand.append(b)
                else:
                    ok = False
            else:
                ok = False
        elif op == 3 and len(cand) >= 2:
            # 合并架次
            i, j = rng.choice(len(cand), size=2, replace=False)
            merged = None
            for g in [cand[i].gtype, cand[j].gtype]:
                nt = Trip(g, cand[i].box_ids + cand[j].box_ids)
                if nt.feasible:
                    merged = nt
                    break
            if merged is not None:
                cand = [c for k, c in enumerate(cand) if k not in (i, j)] + [merged]
            else:
                ok = False
        elif op == 4:
            # 更换机型
            i = int(rng.integers(len(cand)))
            g = ["A", "B", "C"][int(rng.integers(3))]
            nt = Trip(g, cand[i].box_ids)
            if nt.feasible:
                cand[i] = nt
            else:
                ok = False
        else:
            # 局部分割：把一个架次的货箱打散重插
            i = int(rng.integers(len(cand)))
            pool = list(cand.pop(i).box_ids)
            rng.shuffle(pool)
            ok = repair_insert(cand, pool, rng)

        if not ok:
            continue
        new_obj, new_met, new_sched = evaluate(cand)
        d = new_obj - cur_obj
        if d < 0 or rng.random() < np.exp(-d / max(T, 1e-9)):
            cur, cur_obj, cur_met, cur_sched = cand, new_obj, new_met, new_sched
            if cur_obj < best_obj - 1e-12:
                best, best_obj, best_met, best_sched = cand, cur_obj, new_met, new_sched
        T *= cool
        if it % 200 == 0 or it == 1:
            hist.append((it, best_obj, best_met["n_trips"], best_met["energy"],
                         best_met["makespan"], best_met["prio_lateness"],
                         best_met["first_violation"]))
    return best, best_obj, best_met, best_sched, pd.DataFrame(
        hist, columns=["iter", "obj", "n_trips", "energy", "makespan",
                       "prio_lateness", "first_violation"])


# ==================================================================== 输出
def export(trips, sched, met, tag="q2"):
    rows_s = []
    for s in sorted(sched, key=lambda r: r["start"]):
        t = trips[s["trip_idx"]]
        rows_s.append(dict(
            trip_id=f"{tag.upper()}-T{s['trip_idx']+1:02d}", drone=s["drone"],
            gtype=t.gtype, battery=s["battery"],
            start=round(s["start"], 1), stops="->".join(t.stops),
            end=round(s["end"], 1), energy=round(t.energy, 4),
            n_box=len(t.box_ids), mass=round(t.sum_mass, 2),
            soc_end=round(t.soc_end * 100, 2), charge_s=round(t.charge_s, 1),
            boxes="|".join(t.box_ids)))
    df_s = pd.DataFrame(rows_s)
    rows_b = []
    for s in sorted(sched, key=lambda r: r["start"]):
        t = trips[s["trip_idx"]]
        for b in t.box_ids:
            sid = B_SID[BOX_IDX[b]]
            rows_b.append(dict(box=b, trip_id=f"{tag.upper()}-T{s['trip_idx']+1:02d}",
                               sid=sid, deliver=round(s["start"] + t.offset[sid], 1)))
    df_b = pd.DataFrame(rows_b)
    return df_s, df_b


def main(iters=15000, time_limit=240.0):
    t_start = time.time()
    precompute_all_legs()
    print("航段缓存预热完成 %.1fs" % (time.time() - t_start))

    # ---------------- Stage A：容量最优参考解（仅以架次数/路由代价为目标）
    pats = gen_patterns(3)
    print("候选架次模式数：", len(pats))
    tA = time.time()
    chosen, status = stage_a_milp(pats, time_limit=90)
    print("Stage A 状态：%s  用时 %.1fs  选中模式 %d" % (status, time.time() - tA, len(chosen)))
    tripsA = pack_pattern(chosen)
    schedA, metA = greedy_schedule_fast(tripsA)
    print("Stage A 容量最优参考：架次 %d, 能耗 %.2f kWh, 首批超时 %.0f s" %
          (metA["n_trips"], metA["energy"], metA["first_violation"]))

    # ---------------- 时限感知构造：得到首批可行的初始解
    trips0 = construct_initial()
    sched0, met0 = greedy_schedule_fast(trips0)
    print("构造初始解：架次 %d, 能耗 %.2f kWh, 完工 %.0f s, 首批超时 %.0f s" %
          (met0["n_trips"], met0["energy"], met0["makespan"], met0["first_violation"]))

    # ---------------- Stage C: ALNS
    ref = dict(late=max(met0["prio_lateness"], 1.0),
               mk=max(met0["makespan"], 1.0),
               e=max(met0["energy"], 1.0),
               n=max(met0["n_trips"], 1))
    tC = time.time()
    best, best_obj, best_met, best_sched, hist = alns(
        trips0, ref, W_DEFAULT, iters=iters, time_limit=time_limit)
    print("ALNS 用时 %.1fs，目标 %.4f -> %.4f" % (time.time() - tC, hist["obj"].iloc[0], best_obj))
    print("ALNS 指标：", {k: round(v, 2) if isinstance(v, float) else v
                          for k, v in best_met.items()})

    # ---------------- Stage D: CP-SAT 精确调度
    tD = time.time()
    sched_cp, met_cp, st_cp = cp_schedule(best, w_makespan=1.0, w_late=1.0,
                                          time_limit=120)
    print("CP-SAT 调度：%s  用时 %.1fs" % (st_cp, time.time() - tD))
    if sched_cp is not None:
        print("CP-SAT 指标：", {k: round(v, 2) if isinstance(v, float) else v
                                for k, v in met_cp.items()})

    # 选取更优者
    use_cp = (sched_cp is not None and met_cp["first_violation"] <= metA["first_violation"]
              and met_cp["prio_lateness"] <= best_met["prio_lateness"] + 1e-6)
    sched = sched_cp if use_cp else best_sched
    met = met_cp if use_cp else best_met
    metF = solution_full(best, sched)

    # ---------------- 校验与导出
    issues = validate(best, sched)
    print("可行性校验：", "通过" if not issues else issues)
    df_s, df_b = export(best, sched, metF)
    df_s.to_csv(RES / "q2_transport_trips.csv", index=False, encoding="utf-8-sig")
    df_b.to_csv(RES / "q2_box_delivery.csv", index=False, encoding="utf-8-sig")
    hist.to_csv(RES / "q2_alns_convergence.csv", index=False, encoding="utf-8-sig")

    # 资源使用情况
    res_rows = []
    for u in sorted(set(s["drone"] for s in sched)):
        ss = [s for s in sched if s["drone"] == u]
        res_rows.append(dict(drone=u, gtype=best[ss[0]["trip_idx"]].gtype,
                             n_trips=len(ss),
                             busy_s=round(sum(x["end"] - x["start"] for x in ss), 1),
                             first_start=round(min(x["start"] for x in ss), 1),
                             last_end=round(max(x["end"] for x in ss), 1)))
    pd.DataFrame(res_rows).to_csv(RES / "q2_drone_usage.csv", index=False, encoding="utf-8-sig")

    bat_rows = []
    for key in sorted(set(s["batt_key"] for s in sched)):
        ss = [s for s in sched if s["batt_key"] == key]
        tr = [best[x["trip_idx"]] for x in ss]
        bat_rows.append(dict(battery=f"{key[0]}{key[1]+1}", gtype=key[0], n_trips=len(ss),
                             total_energy=round(sum(t.energy for t in tr), 4),
                             min_soc=round(min(t.soc_end for t in tr) * 100, 2),
                             charge_total_s=round(sum(t.charge_s for t in tr), 1),
                             last_free=round(max(x["end"] + best[x["trip_idx"]].charge_s
                                                 for x in ss), 1)))
    pd.DataFrame(bat_rows).to_csv(RES / "q2_battery_usage.csv", index=False, encoding="utf-8-sig")

    summary = dict(
        n_trips=len(best), energy=round(sum(t.energy for t in best), 4),
        makespan=round(metF["makespan"], 1),
        makespan_h=round(metF["makespan"] / 3600, 3),
        prio_lateness=round(metF["prio_lateness"], 1),
        late_boxes=metF["late_boxes"], on_time_rate=round(metF["on_time_rate"], 4),
        first_violation=round(metF["first_violation"], 2),
        mean_deliver=round(metF["mean_deliver"], 1),
        n_drones_used=len(set(s["drone"] for s in sched)),
        n_batteries_used=len(set(s["batt_key"] for s in sched)),
        alns_hist=len(hist), status_cp=st_cp, status_a=status,
        feasible_check="通过" if not issues else "; ".join(issues),
        runtime_s=round(time.time() - t_start, 1),
    )
    with open(RES / "q2_results.json", "w", encoding="utf-8") as f:
        json.dump(dict(summary=summary,
                       trips=[{k: v for k, v in r.items()} for r in df_s.to_dict("records")]),
                  f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return best, sched, metF


def solution_full(trips, sched):
    return solution_metrics(trips, sched)


if __name__ == "__main__":
    main()
