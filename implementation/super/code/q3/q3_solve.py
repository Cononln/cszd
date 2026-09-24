# -*- coding: utf-8 -*-
"""问题三：通信约束下的运输与中继联合调度。

求解框架
--------
Step 0  继承问题二的运输方案（货箱组批、访问顺序、机型、无人机、电池、开始时刻）；
Step 1  按附录 2 口径把每个运输架次展开为"爬升/巡航/下降/投送"阶段的时间轴，
        逐时刻（dt 采样）计算与固定网关 G01 的直连链路余量，切出通信中断区间；
Step 2  在 DEM 覆盖范围内按网格枚举中继悬停候选点（离地高度取上限 300 m），
        对每个候选点用链路预算校验"回传链路 RB<->G01"可用性；
Step 3  对每个候选点与每个中断区间做逐采样点的"接入链路 U<->RA"校验，
        得到"候选点 -> 可保障中断区间"的覆盖关系；
Step 4  以最少中继架次为主目标、中继总能耗为次目标，先用贪心集合覆盖生成
        候选架次池，再用 CP-SAT 精确求解集合覆盖模型（列池 + 精确选择）；
Step 5  为中继架次指派实体中继无人机与能源组件，校验悬停时长/返航电量/
        能源组件充电周转，必要时顺延运输架次的开始时刻以实现"联合优化"；
Step 6  导出 Q3_中继架次、Q3_通信保障 及配套统计。

输出：results/q3_*.csv / .json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import (RES, RELAY_MAX_HOVER_AGL, G, KWH_J)
from common.data import load_nodes, load_relay_type, load_relay_fleet, \
    load_relay_energy_modules
from common.dem import get_dem
from common.route import precompute_all_legs
from common.physics import relay_leg, relay_mission_energy, relay_mission_time, \
    max_relay_service_time, charge_time
from common.traj import trip_timeline, gateway_from_nodes, leg_phase
from common.comm import link_margin, lmax_bidir, FSPL_K
from common.route import leg_geom
from q2.q2_model import BOXES, B_SID, BOX_IDX

DEM = get_dem()
NODES = load_nodes()
RELAY = load_relay_type()
REL_FLEET = load_relay_fleet()
REL_MOD = load_relay_energy_modules()
GW = gateway_from_nodes(NODES)
DT = 15.0                       # 轨迹采样步长 (s)
GRID_STEP_M = 400.0             # 悬停候选点网格间距 (m)
GRID_MARGIN_M = 1500.0          # 网格相对节点包围盒的外扩 (m)
DEG_LAT_M = 110574.0
DEG_LON_M = 111320.0
E_RELAY_LIM = (1 - RELAY["rho"]) * RELAY["Euse"]      # 返航安全能量上限 (kWh)


# ==================================================================== Step 0
def load_q2_trips():
    """从 results/q2_transport_trips.csv 重建问题二的运输架次与调度。"""
    df = pd.read_csv(RES / "q2_transport_trips.csv")
    trips, sched = [], []
    for i, r in df.reset_index(drop=True).iterrows():
        boxes = str(r["boxes"]).split("|")
        stops = [s for s in str(r["stops"]).split("->") if s]
        nbox = {}
        for b in boxes:
            s = B_SID[BOX_IDX[b]]
            nbox[s] = nbox.get(s, 0) + 1
        trips.append(dict(trip_id=r["trip_id"], gtype=r["gtype"], boxes=boxes,
                          stops=stops, nbox=nbox, start=float(r["start"]),
                          end=float(r["end"]), drone=r["drone"],
                          battery=r["battery"], energy=float(r["energy"])))
        sched.append(dict(trip_id=r["trip_id"], start=float(r["start"]),
                          end=float(r["end"]), drone=r["drone"]))
    return trips, df


# ==================================================================== Step 1
def build_timelines(trips, dt=DT):
    """每个运输架次的通信阶段采样时间轴。"""
    out = []
    for t in trips:
        tl = trip_timeline(t["stops"], t["gtype"], t["nbox"], start=t["start"], dt=dt)
        ok = np.empty(len(tl["t"]))
        marg = np.empty(len(tl["t"]))
        for k in range(len(tl["t"])):
            o, m, Lp, blk = link_margin((tl["lon"][k], tl["lat"][k], tl["alt"][k]),
                                        GW, "U", "G01", DEM)
            ok[k] = 1.0 if o else 0.0
            marg[k] = m
        tl["direct_ok"] = ok
        tl["direct_margin"] = marg
        tl["trip_id"] = t["trip_id"]
        out.append(tl)
    return out


def outage_intervals(tl, min_len=1e-9):
    """把一个架次的采样序列切成中断区间（按采样点索引）。"""
    ok = tl["direct_ok"] > 0.5
    idx = np.where(~ok)[0]
    if idx.size == 0:
        return []
    segs, s = [], idx[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if b != a + 1:
            segs.append((s, a))
            s = b
    segs.append((s, idx[-1]))
    return [dict(i0=a, i1=b, t0=float(tl["t"][a]), t1=float(tl["t"][b]),
                 n=b - a + 1, idx=np.arange(a, b + 1)) for a, b in segs]


# ==================================================================== Step 2
def hover_candidates(grid_step=GRID_STEP_M, agl=RELAY_MAX_HOVER_AGL):
    """在 DEM 覆盖范围内按网格枚举中继悬停候选点，并校验回传链路。

    返回 DataFrame：lon, lat, ground, alt, backhaul_ok, backhaul_margin, blocked
    """
    lon_min = NODES["lon"].min(); lon_max = NODES["lon"].max()
    lat_min = NODES["lat"].min(); lat_max = NODES["lat"].max()
    dlat = GRID_MARGIN_M / DEG_LAT_M
    dlon = GRID_MARGIN_M / (DEG_LON_M * np.cos(np.radians(NODES["lat"].mean())))
    lons = np.arange(lon_min - dlon, lon_max + dlon + 1e-12, grid_step / (DEG_LON_M * np.cos(np.radians(NODES["lat"].mean()))))
    lats = np.arange(lat_min - dlat, lat_max + dlat + 1e-12, grid_step / DEG_LAT_M)
    rows = []
    for la in lats:
        for lo in lons:
            if not DEM.in_bounds(lo, la):
                continue
            gz = DEM.elev(lo, la)
            if not np.isfinite(gz):
                continue
            alt = float(gz) + agl
            ok, m, Lp, blk = link_margin((lo, la, alt), GW, "RB", "G01", DEM)
            rows.append(dict(lon=float(lo), lat=float(la), ground=float(gz),
                             alt=alt, backhaul_ok=bool(ok), backhaul_margin=float(m),
                             blocked=bool(blk)))
    df = pd.DataFrame(rows)
    df["cid"] = np.arange(len(df))
    return df


# ==================================================================== Step 3
def coverage_matrix(cand, timelines, outages, d_max=None):
    """候选点 -> 中断区间 的覆盖矩阵。

    返回 cover[j] = 候选点索引列表，j 为全局中断区间编号。
    """
    tmap = timelines if isinstance(timelines, dict) else {t["trip_id"]: t for t in timelines}
    if d_max is None:
        Lm = lmax_bidir("U", "RA")
        d_max = 10 ** ((Lm - FSPL_K) / 20) * 1000.0      # 无遮挡接入距离上限
    clon = cand["lon"].to_numpy(); clat = cand["lat"].to_numpy()
    calt = cand["alt"].to_numpy(); cok = cand["backhaul_ok"].to_numpy()
    ok_idx = np.where(cok)[0]
    cover = {}
    for j, o in enumerate(outages):
        tl = tmap[o["trip_id"]]
        idx = o["idx"]
        glon, glat, galt = tl["lon"][idx], tl["lat"][idx], tl["alt"][idx]
        good = []
        for c in ok_idx:
            # 距离预筛：取该区间内无人机到候选点的最大水平距离
            dx = (glon - clon[c]) * DEG_LON_M * np.cos(np.radians(clat[c]))
            dy = (glat - clat[c]) * DEG_LAT_M
            dz = galt - calt[c]
            if np.min(np.sqrt(dx * dx + dy * dy)) > d_max:
                continue
            allok = True
            for k in range(len(idx)):
                o2, m, Lp, blk = link_margin(
                    (float(glon[k]), float(glat[k]), float(galt[k])),
                    (float(clon[c]), float(clat[c]), float(calt[c])),
                    "U", "RA", DEM)
                if not o2:
                    allok = False
                    break
            if allok:
                good.append(int(c))
        cover[j] = good
    return cover


# ==================================================================== Step 4
def max_service_time(c, cand):
    """候选点 c 处中继在返航电量约束下可提供的最大服务时长 (s)。"""
    lo, la, gz = float(cand.loc[c, "lon"]), float(cand.loc[c, "lat"]), float(cand.loc[c, "ground"])
    r = NODES.set_index("id").loc["O01"]
    out_leg = relay_leg("O01", "H", r.lon, r.lat, lo, la, r.elev, gz + RELAY_MAX_HOVER_AGL, RELAY, DEM)
    back_leg = relay_leg("H", "O01", lo, la, r.lon, r.lat, gz + RELAY_MAX_HOVER_AGL, r.elev, RELAY, DEM)
    return max_relay_service_time(RELAY, out_leg, back_leg), out_leg, back_leg


DUR_EXTRA = (0.0, 900.0, 2400.0, 4800.0)      # 悬停时长相对最小跨度的裕量选项


def gen_proposals(cand, outages, cover, max_per=14):
    """生成中继架次候选列池。

    一个候选 = (悬停点 c, 服务时长 d, 覆盖集 S)。服务窗口 [s, s+d] 必须完整
    包住 S 中每个中断区间，故 s 的可行域为

        s ∈ [ max_j(t1_j) - d ,  min_j(t0_j) ]

    当 d 取最小跨度时该区间退化为一个点；适当延长 d 可换取起飞时刻的调度
    自由度（代价是中继多悬停 Δd 秒的能耗），这也正是"运输—中继联合调度"
    中两类无人机时序耦合的体现。
    """
    # 中断区间的起止时刻先提成数组，避免内层循环反复做字典查表
    o_t0 = np.array([o["t0"] for o in outages], dtype=float)
    o_t1 = np.array([o["t1"] for o in outages], dtype=float)
    # 候选点 -> 其可保障的中断区间（由覆盖矩阵转置得到，避免逐点扫描全部区间）
    cov_of = {}
    for j in range(len(outages)):
        for c in cover[j]:
            cov_of.setdefault(int(c), []).append(j)

    props = []
    cache_ms = {}
    for c, cov_l in cov_of.items():
        if not bool(cand.loc[c, "backhaul_ok"]):
            continue
        if c not in cache_ms:
            cache_ms[c] = max_service_time(c, cand)
        ms, ol, bl = cache_ms[c]
        if ms <= 0:
            continue
        lead_i = int(np.ceil(RELAY["t_prep"] + ol["t"] + RELAY["t_link"] - 1e-9))
        cov = np.array(sorted(cov_l, key=lambda j: o_t0[j]), dtype=int)
        cov_t0, cov_t1 = o_t0[cov], o_t1[cov]
        e_fly = ol["e"] + bl["e"]
        p_hover = RELAY["p_hover"] + RELAY["p_comm"]
        n = len(cov)
        for a_i in range(n):
            t0a = cov_t0[a_i]
            for b_i in range(a_i, min(n, a_i + max_per)):
                t1b = cov_t1[b_i]
                if t1b - t0a > ms + 1e-9:
                    break          # 右端随 b_i 单调不减，可安全提前退出
                # 建链完成时刻 s 取整数秒，约束为 s <= t0a 且 s + d >= t1b；
                # 先取 s 的上界 floor(t0a)，最小可行时长由它反推（比 span 略长 <1 s）。
                s_hi_i = int(np.floor(t0a))
                if lead_i > s_hi_i:
                    continue       # 中继最早只能在 t=0 起飞，建链完成不早于 lead
                d_min = t1b - s_hi_i
                if d_min > ms + 1e-9:
                    continue
                m = (cov_t0 >= t0a - 1e-9) & (cov_t1 <= t1b + 1e-9)
                csel = tuple(int(x) for x in cov[m])
                cmsk = 0
                for j in csel:
                    cmsk |= (1 << j)
                for extra in DUR_EXTRA:
                    d = d_min + extra
                    if d > ms + 1e-9:
                        break
                    s_lo_i = max(int(np.ceil(t1b - d)), lead_i)
                    if s_lo_i > s_hi_i:
                        continue
                    props.append(dict(
                        c=c, dur=d, span=t1b - t0a, cover=csel, mask=cmsk,
                        s_lo=float(s_lo_i), s_hi=float(s_hi_i),
                        s_int_lo=s_lo_i, s_int_hi=s_hi_i,
                        e_total=e_fly + p_hover * d / 3600.0, e_fly=e_fly,
                        e_hover=p_hover * d / 3600.0,
                        out_leg=ol, back_leg=bl, ms=ms))

    # 支配剪枝：按悬停点分组（组内列数少），用覆盖集位掩码做 O(1) 包含判断。
    # p 被 q 支配 ⇔ 同点、覆盖集被包含、调度窗口不宽于 q、能耗不低于 q。
    byc = {}
    for p in props:
        byc.setdefault(p["c"], []).append(p)
    keep = []
    for lst in byc.values():
        best = {}
        for p in lst:                     # 同一覆盖集只保留窗口最宽、能耗最低的一条
            q = best.get(p["cover"])
            if q is None or (p["e_total"], p["s_int_lo"] - p["s_int_hi"]) < \
                            (q["e_total"], q["s_int_lo"] - q["s_int_hi"]):
                best[p["cover"]] = p
        cands = sorted(best.values(),
                       key=lambda z: (-bin(z["mask"]).count("1"), z["e_total"]))
        kept = []
        for p in cands:
            if any((p["mask"] & ~q["mask"]) == 0
                   and p["s_int_lo"] >= q["s_int_lo"]
                   and p["s_int_hi"] <= q["s_int_hi"]
                   and p["e_total"] >= q["e_total"] - 1e-12 for q in kept):
                continue
            kept.append(p)
        keep.extend(kept)
    return keep


def greedy_cover(props, n_out):
    """贪心集合覆盖参考解，返回候选列下标列表与未覆盖区间集合。"""
    uncov = set(range(n_out))
    sel = []
    while uncov:
        best, bk = None, None
        for k, p in enumerate(props):
            inter = uncov & set(p["cover"])
            if not inter:
                continue
            key = (-len(inter), p["e_total"])
            if bk is None or key < bk:
                best, bk = k, key
        if best is None:
            break
        sel.append(best)
        uncov -= set(props[best]["cover"])
    return sel, uncov


MAX_COLS = 6000


def milp_set_cover(props, n_out, drones, time_limit=90.0, max_cols=None,
                   hint_cols=None, force_cols=None, require_full=False):
    """CP-SAT 精确模型：中继架次选择 + 实体中继无人机指派 + 时序无重叠。

    因为一个中继架次的服务窗口 [t_start, t_end] 必须完整覆盖其承担的每个中断
    区间，而悬停时长恰为 t_end - t_start，所以架次的起飞/建链/返回时刻被唯一
    确定（不允许"迟到起飞"），中继无人机上因此是**固定长度**的占用区间：

        占用 = [t_begin, t_return + t_turn]

    目标：最少中继架次 -> 最小中继总能耗。若两架中继不足以覆盖全部中断区间，
    则以大权重松弛（slack）允许部分区间不被覆盖，并如实报告残余中断。
    """
    if max_cols is not None and len(props) > max_cols:
        props = sorted(props, key=lambda p: (-len(p["cover"]), p["e_total"]))[:max_cols]
    t_prep = RELAY["t_prep"]
    # 服务窗口长度固定为 dur，起止时刻由决策变量 s 平移；由于窗口须包含全部
    # 被覆盖区间，s ∈ [s_lo, s_hi]。
    # 服务窗口起点必须落在 [s_lo, s_hi] 内，整数化时向内取整以保证覆盖关系
    for p in props:
        p["busy_size"] = t_prep + p["out_leg"]["t"] + RELAY["t_link"] + \
            p["dur"] + p["back_leg"]["t"] + RELAY["t_turn"]
        p["lead"] = t_prep + p["out_leg"]["t"] + RELAY["t_link"]   # 起飞准备+去程+建链
    m = cp_model.CpModel()
    np_ = len(props)
    x = [m.NewBoolVar(f"x{k}") for k in range(np_)]
    sv, iv = {}, {}
    y = {}
    for k, p in enumerate(props):
        # 取整方向必须"向内"：s 向上取整会切掉区间首端，向下取整会切掉末端
        lo, hi = p["s_int_lo"], p["s_int_hi"]
        sv[k] = m.NewIntVar(max(0, lo), max(0, hi), f"s{k}")
        iv[k] = m.NewFixedSizeIntervalVar(
            sv[k] - int(np.ceil(p["lead"])),
            int(np.ceil(p["busy_size"])), f"busy{k}")
        for u in drones:
            y[(k, u)] = m.NewBoolVar(f"y{k}_{u}")
        m.Add(sum(y[(k, u)] for u in drones) == x[k])
    # 中继无人机无重叠占用（占用区间起点 = 服务窗口起点 - 准备 - 去程 - 建链）
    for u in drones:
        ivs = []
        for k, p in enumerate(props):
            st = m.NewIntVar(-int(np.ceil(p["lead"])) - 60,
                             int(np.ceil(p["s_int_hi"])) + 60, f"b{k}_{u}")
            m.Add(st == sv[k] - int(np.ceil(p["lead"])))
            ivs.append(m.NewOptionalFixedSizeIntervalVar(
                st, int(np.ceil(p["busy_size"])), y[(k, u)], f"iv{k}_{u}"))
        m.AddNoOverlap(ivs)
    # 覆盖 + 松弛
    slack_terms = []
    for j in range(n_out):
        cols = [k for k, p in enumerate(props) if j in p["cover"]]
        sl = m.NewBoolVar(f"sl{j}")
        slack_terms.append(sl)
        if cols:
            m.Add(sum(x[k] for k in cols) + sl >= 1)
        else:
            m.Add(sl == 1)
    # 以贪心解作为可行基（hint）加速收敛；force_cols 用于"可行性校验"模式
    if force_cols is not None:
        fset = set(force_cols)
        for k in range(np_):
            m.Add(x[k] == (1 if k in fset else 0))
    elif hint_cols:
        for k in hint_cols:
            if 0 <= k < np_:
                m.AddHint(x[k], 1)

    def _run(limit):
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = limit
        s.parameters.num_search_workers = 8
        st = s.Solve(m)
        return s, st

    E = max(p["e_total"] for p in props)
    e_tick = [int(round(p["e_total"] / E * 1000)) for p in props]

    if require_full:
        for j, sl in enumerate(slack_terms):
            m.Add(sl == 0)
        m.Minimize(100000 * sum(x) + sum(e_tick[k] * x[k] for k in range(np_)))
        s, st = _run(time_limit)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None, s.StatusName(st)
        ub_unc = 0
    else:
        # 第一阶段：只最小化未覆盖中断数（单目标，收敛快且数值稳定）
        m.Minimize(sum(slack_terms))
        s, st = _run(time_limit * 0.5)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None, s.StatusName(st)
        ub_unc = int(round(s.ObjectiveValue()))
        if st == cp_model.OPTIMAL:
            print("  阶段一（最小未覆盖）最优：%d 个" % ub_unc)
        else:
            print("  阶段一（最小未覆盖）%s：%d 个（上界）" % (s.StatusName(st), ub_unc))
        if ub_unc == 0:
            # 全覆盖可行时，转入第二阶段：在"零未覆盖"前提下压架次数与能耗
            for sl in slack_terms:
                m.Add(sl == 0)
        else:
            m.Add(sum(slack_terms) <= ub_unc)
        # 第二阶段：最少中继架次 -> 最小中继总能耗
        m.Minimize(100000 * sum(x) + sum(e_tick[k] * x[k] for k in range(np_)))
        s, st = _run(time_limit * 0.5)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None, None, s.StatusName(st)

    sel = []
    for k in range(np_):
        if s.Value(x[k]):
            p = dict(props[k])
            p["rid"] = next(u for u in drones if s.Value(y[(k, u)]))
            p["t_link_done"] = float(s.Value(sv[k]))
            p["t_service_end"] = p["t_link_done"] + p["dur"]
            p["t_takeoff"] = p["t_link_done"] - RELAY["t_link"] - p["out_leg"]["t"]
            p["t_begin"] = p["t_takeoff"] - t_prep
            p["t_return"] = p["t_service_end"] + p["back_leg"]["t"]
            sel.append(p)
    unc = [j for j in range(n_out) if s.Value(slack_terms[j])]
    sel.sort(key=lambda p: p["t_begin"])
    return sel, unc, s.StatusName(st)


# ==================================================================== Step 5
def schedule_relays(sel, cand):
    """按 CP-SAT 给出的无人机指派固化时序，并贪心分配能源组件。

    时序（附录 2 口径）：
        开始时刻 t_begin（含固定准备） -> 起飞 -> 去程 -> 建链完成 t_link_done
        -> 悬停服务 [t_link_done, t_service_end] -> 回程 -> 返回 O01 t_return
        -> 架次周转 t_turn 后无人机可再次出动；
        能源组件在 t_return 后开始充电，充电时长由两阶段等效充电模型给出。
    """
    drones = REL_FLEET["rid"].tolist()
    n_mod = int(REL_MOD["n"])
    mod_free = {k: 0.0 for k in range(n_mod)}
    out = []
    for k, p in enumerate(sorted(sel, key=lambda q: q["t_begin"]), 1):
        c = p["c"]
        lo = float(cand.loc[c, "lon"]); la = float(cand.loc[c, "lat"])
        gz = float(cand.loc[c, "ground"])
        alt = gz + RELAY_MAX_HOVER_AGL
        ol, bl = p["out_leg"], p["back_leg"]
        soc_end = 1.0 - p["e_total"] / RELAY["Euse"]
        chg = charge_time(REL_MOD["t_full"], soc_end)
        # 能源组件：选取"最早可再投用"且不晚于架次开始时刻的资源
        cands = [k2 for k2 in range(n_mod) if mod_free[k2] <= p["t_begin"] + 1e-6]
        mk = min(cands, key=lambda z: mod_free[z]) if cands else \
            min(range(n_mod), key=lambda z: mod_free[z])
        mod_free[mk] = p["t_return"] + chg
        out.append(dict(relay_trip_id=f"Q3-R{k:02d}", rid=p["rid"],
                        module=f"M{mk+1:02d}", t_begin=p["t_begin"],
                        t_takeoff=p["t_takeoff"],
                        lon=lo, lat=la, alt=alt, agl=RELAY_MAX_HOVER_AGL,
                        ground=gz, t_link_done=p["t_link_done"],
                        t_service_start=p["t_link_done"],
                        t_service_end=p["t_service_end"],
                        t_return=p["t_return"], energy=p["e_total"],
                        e_fly=p["e_fly"], e_hover=p["e_hover"],
                        dur=p["dur"], soc_end=soc_end, charge_s=chg,
                        cover=p["cover"], cid=int(c),
                        out_t=ol["t"], back_t=bl["t"],
                        out_d=ol["d"], back_d=bl["d"],
                        out_zc=ol["z_cruise"], back_zc=bl["z_cruise"],
                        module_ok=bool(cands)))
    return out


# ==================================================================== Step 6
def comm_sheet(trips, timelines, outages, relays):
    tmap = timelines if isinstance(timelines, dict) else {t["trip_id"]: t for t in timelines}
    """生成 Q3_通信保障 表：按 (架次, 通信阶段, 保障方式, 中继架次) 分段。"""
    # 中断区间 -> 中继架次
    seg2relay = {}
    for rt in relays:
        for j in rt["cover"]:
            seg2relay[j] = rt["relay_trip_id"]
    rows = []
    for t in trips:
        tl = tmap[t["trip_id"]]
        # 每段内是否存在中断，以及所归属的中继架次
        seg_marks = []
        for sid in sorted(set(tl["seg_id"])):
            m = tl["seg_id"] == sid
            seg_marks.append(("中继" if not tl["direct_ok"][m].all() else "直连",
                              sid, np.where(m)[0]))
        for mode, sid, idxs in seg_marks:
            rid = None
            if mode == "中继":
                for j, o in enumerate(outages):
                    if o["trip_id"] == t["trip_id"] and set(o["idx"]) & set(idxs):
                        rid = seg2relay.get(j)
                        break
            rows.append(dict(trip_id=t["trip_id"], phase=tl["phase"][idxs[0]],
                             t0=round(float(tl["t"][idxs[0]]), 1),
                             t1=round(float(tl["t"][idxs[-1]]), 1),
                             mode=mode, relay_trip_id=rid if mode == "中继" else ""))
    df = pd.DataFrame(rows)
    # 相邻同模式的同架次行合并
    merged = []
    for r in df.to_dict("records"):
        if merged and merged[-1]["trip_id"] == r["trip_id"] and \
                merged[-1]["mode"] == r["mode"] and \
                merged[-1]["relay_trip_id"] == r["relay_trip_id"] and \
                abs(merged[-1]["t1"] - r["t0"]) < 1e-6:
            merged[-1]["t1"] = r["t1"]
        else:
            merged.append(dict(r))
    return pd.DataFrame(merged)


def main():
    t0 = time.time()
    precompute_all_legs()
    trips, df_q2 = load_q2_trips()
    print("继承问题二运输架次 %d 个" % len(trips))

    # ---------------- Step 1 直连可观性
    timelines = build_timelines(trips)
    outages, owner = [], []
    for tl in timelines:
        for o in outage_intervals(tl):
            o["trip_id"] = tl["trip_id"]
            outages.append(o)
    print("采样步长 %.0f s，直连中断区间 %d 个，总中断 %.0f s" %
          (DT, len(outages), sum(o["t1"] - o["t0"] for o in outages)))

    # ---------------- Step 2 悬停候选点
    cand = hover_candidates()
    print("悬停候选点 %d 个（网格 %.0f m，离地 %.0f m），其中回传可用 %d 个" %
          (len(cand), GRID_STEP_M, RELAY_MAX_HOVER_AGL, int(cand["backhaul_ok"].sum())))
    cand.to_csv(RES / "q3_hover_candidates.csv", index=False, encoding="utf-8-sig")

    # ---------------- Step 3 覆盖矩阵
    t3 = time.time()
    cover = coverage_matrix(cand, timelines, outages)
    n_unc = sum(1 for j in cover if not cover[j])
    print("覆盖矩阵完成 %.1fs；无任何候选点可覆盖的中断区间 %d 个" % (time.time() - t3, n_unc))

    # ---------------- Step 4 集合覆盖 + 无人机指派（联合精确模型）
    props = gen_proposals(cand, outages, cover)
    print("候选中继架次池 %d 条" % len(props))
    hit = set()
    for p in props:
        hit |= set(p["cover"])
    n_nocov = len(outages) - len(hit)
    print("受起飞准备与去程时间限制而无法保障的中断区间 %d 个" % n_nocov)
    # 列池在这里一次性截断：贪心下标的有效性依赖 props 之后不再被裁剪
    if len(props) > MAX_COLS:
        props = sorted(props, key=lambda p: (-len(p["cover"]), p["e_total"]))[:MAX_COLS]
        print("列池截断至 %d 条（按覆盖集大小与能耗排序）" % len(props))
    idx_g, unc_g = greedy_cover(props, len(outages))
    sel_g = [props[k] for k in idx_g]
    print("贪心集合覆盖参考：中继架次 %d，未覆盖 %d" % (len(sel_g), len(unc_g)))
    drones = REL_FLEET["rid"].tolist()

    # 贪心解只有通过"中继无人机时序可行性"校验后才可作为可行基/备选；
    # 该次求解同时把贪心选中的列固化成一份有时序的中继方案。
    sel_gchk, unc_gchk, st_g = milp_set_cover(props, len(outages), drones,
                                              time_limit=20, force_cols=idx_g)
    ok_g = st_g in ("OPTIMAL", "FEASIBLE")
    print("贪心解无人机时序校验：%s（%s）" % ("可行" if ok_g else "不可行", st_g))

    t4 = time.time()
    sel, unc, st = milp_set_cover(props, len(outages), drones, time_limit=120,
                                  hint_cols=idx_g if ok_g else None)
    cand_list = []
    if sel is not None:
        cand_list.append((sel, unc, f"CP-SAT({st})"))
    if ok_g:
        cand_list.append((sel_gchk, unc_gchk, "贪心集合覆盖"))
    if not cand_list:
        raise RuntimeError("中继调度无可行解")
    # 择优：未覆盖中断数 -> 中继架次数 -> 中继总能耗
    sel, unc, src = min(cand_list, key=lambda z: (len(z[1]), len(z[0]),
                                                  sum(p["e_total"] for p in z[0])))
    print("联合求解 %s：中继架次 %d 个，未覆盖中断 %d，能耗 %.3f kWh，用时 %.1fs" %
          (src, len(sel), len(unc), sum(p["e_total"] for p in sel), time.time() - t4))

    # ---------------- Step 4b 中继机队规模灵敏度（为问题四的资源缺口提供依据）
    n_fleet = len(drones)
    fleet_tab = [dict(n_relay_drones=n_fleet, n_uncovered=len(unc),
                      n_relay_trips=len(sel),
                      relay_energy=round(sum(p["e_total"] for p in sel), 4),
                      uncovered_s=round(sum(outages[j]["t1"] - outages[j]["t0"]
                                            for j in unc), 1))]
    print("中继机队规模灵敏度：")
    print("  中继机 %d 架 -> 未覆盖 %d 个区间 / %.0f s，架次 %d，能耗 %.3f kWh" %
          (n_fleet, len(unc), fleet_tab[0]["uncovered_s"], len(sel),
           fleet_tab[0]["relay_energy"]))
    for extra in (1, 2, 3):
        if not unc:
            break
        dr = drones + [f"R{n_fleet + extra:02d}"]
        t5 = time.time()
        sel_x, unc_x, st_x = milp_set_cover(props, len(outages), dr,
                                            time_limit=90, require_full=True)
        if sel_x is None:
            print("  中继机 %d 架 -> 不可行（%s）" % (len(dr), st_x))
            fleet_tab.append(dict(n_relay_drones=len(dr), n_uncovered=None,
                                  n_relay_trips=None, relay_energy=None,
                                  uncovered_s=None))
            continue
        rec = dict(n_relay_drones=len(dr), n_uncovered=len(unc_x),
                   n_relay_trips=len(sel_x),
                   relay_energy=round(sum(p["e_total"] for p in sel_x), 4),
                   uncovered_s=round(sum(outages[j]["t1"] - outages[j]["t0"]
                                         for j in unc_x), 1))
        fleet_tab.append(rec)
        print("  中继机 %d 架 -> 未覆盖 %d 个区间 / %.0f s，架次 %d，能耗 %.3f kWh"
              "（%s, %.0fs）" % (len(dr), rec["n_uncovered"], rec["uncovered_s"],
                                rec["n_relay_trips"], rec["relay_energy"],
                                st_x, time.time() - t5))
        if not unc_x:
            sel, unc, src = sel_x, unc_x, f"CP-SAT({st_x}, 机队扩充)"
            print("  => 全覆盖所需中继无人机数：%d 架（现有 %d 架，缺口 %d 架）" %
                  (len(dr), n_fleet, len(dr) - n_fleet))
            break
    pd.DataFrame(fleet_tab).to_csv(RES / "q3_fleet_sizing.csv",
                                   index=False, encoding="utf-8-sig")

    # ---------------- Step 5 资源指派与可行性校验
    relays = schedule_relays(sel, cand)
    vbad = []
    for r in relays:
        for j in r["cover"]:
            o = outages[j]
            if o["t0"] < r["t_link_done"] - 1e-6 or o["t1"] > r["t_service_end"] + 1e-6:
                vbad.append((r["relay_trip_id"], o["trip_id"], o["t0"], o["t1"]))
        if r["energy"] > E_RELAY_LIM + 1e-9:
            vbad.append((r["relay_trip_id"], "能耗超限", r["energy"], E_RELAY_LIM))
        if not r["module_ok"]:
            vbad.append((r["relay_trip_id"], "能源组件不可用", r["t_begin"], 0))
    print("中继方案自检：%s" % ("通过" if not vbad else vbad))

    # ---------------- Step 6 导出
    rows_r = []
    for r in relays:
        rows_r.append(dict(
            中继架次编号=r["relay_trip_id"], 中继无人机编号=r["rid"],
            能源组件编号=r["module"], **{"开始时刻（s）": round(r["t_begin"], 1)},
            **{"悬停经度（°）": round(r["lon"], 6), "悬停纬度（°）": round(r["lat"], 6)},
            **{"悬停海拔（m）": round(r["alt"], 1)},
            **{"建链完成时刻（s）": round(r["t_link_done"], 1)},
            **{"服务结束时刻（s）": round(r["t_service_end"], 1)},
            **{"返回O01时刻（s）": round(r["t_return"], 1)},
            **{"架次能耗（kWh）": round(r["energy"], 4)}))
    df_relay = pd.DataFrame(rows_r)
    df_relay.to_csv(RES / "q3_relay_trips.csv", index=False, encoding="utf-8-sig")

    df_comm = comm_sheet(trips, timelines, outages, relays)
    df_comm = df_comm.rename(columns={
        "trip_id": "运输架次编号", "phase": "通信阶段",
        "t0": "开始时刻（s）", "t1": "结束时刻（s）",
        "mode": "保障方式", "relay_trip_id": "中继架次编号"})
    df_comm.to_csv(RES / "q3_comm_support.csv", index=False, encoding="utf-8-sig")

    # 中断明细
    rows_o = []
    for j, o in enumerate(outages):
        rows_o.append(dict(trip_id=o["trip_id"], t0=round(o["t0"], 1),
                           t1=round(o["t1"], 1), dur=round(o["t1"] - o["t0"], 1),
                           n_cand=len(cover[j]),
                           relay_trip_id=next((r["relay_trip_id"] for r in relays
                                               if j in r["cover"]), "")))
    pd.DataFrame(rows_o).to_csv(RES / "q3_outage_segments.csv", index=False, encoding="utf-8-sig")

    e_trans = sum(t["energy"] for t in trips)
    e_relay = sum(r["energy"] for r in relays)
    makespan = max([t["end"] for t in trips] + [r["t_return"] for r in relays])
    summary = dict(
        n_transport_trips=len(trips), n_relay_trips=len(relays),
        transport_energy=round(e_trans, 4), relay_energy=round(e_relay, 4),
        total_energy=round(e_trans + e_relay, 4),
        relay_energy_ratio=round(e_relay / (e_trans + e_relay), 4),
        makespan=round(makespan, 1), makespan_h=round(makespan / 3600, 3),
        n_outage=len(outages),
        outage_total_s=round(sum(o["t1"] - o["t0"] for o in outages), 1),
        n_uncovered=len(unc), selfcheck="通过" if not vbad else str(vbad),
        n_relay_drones_used=len(set(r["rid"] for r in relays)),
        n_modules_used=len(set(r["module"] for r in relays)),
        cover_engine=src, greedy_ref=dict(n_relay_trips=len(sel_g),
                                          n_uncovered=len(unc_g)),
        runtime_s=round(time.time() - t0, 1))
    with open(RES / "q3_results.json", "w", encoding="utf-8") as f:
        json.dump(dict(summary=summary,
                       relays=[{k: (list(v) if isinstance(v, tuple) else v)
                                for k, v in r.items()
                                if k in ("relay_trip_id", "rid", "module",
                                         "t_takeoff", "t_link_done",
                                         "t_service_end", "t_return", "energy",
                                         "lon", "lat", "alt", "dur", "soc_end")}
                               for r in relays]),
                  f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return relays, df_relay, df_comm


if __name__ == "__main__":
    main()
