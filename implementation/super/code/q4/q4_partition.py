# -*- coding: utf-8 -*-
"""问题四：救援任务分区与资源配置优化。

求解框架
--------
Step 1  由问题二的运输架次提取"服务区耦合关系"：同一架次访问的多个服务区
        必须同组；用并查集求传递闭包，得到若干"不可分割原子"；
Step 2  对原子集合做**合法划分全枚举**（2 组与 3 组，每组非空）；
Step 3  对每个划分中的每个任务组，独立核算执行本组全部运输与通信保障任务
        所需的资源：
          运输无人机(按机型)  —— 固定区间上的区间图着色（最少机器数 = 最大并发数）
          共享电池(按机型)    —— 按开始时刻贪心分配"最早可用"电池（含两阶段充电周转）
          中继无人机          —— 中继架次占用区间上的区间图着色
          中继能源组件        —— 同共享电池的周转分配
        跨组不得调配，故涉及多组的中继架次须在每组内各自复制一份；
Step 4  多目标评价：构造 5 项指标（配置规模、资源冗余、组间均衡、库存缺口、
        架次效率），熵权法定权 + TOPSIS 排序，给出 2 组/3 组分区下的推荐方案；
Step 5  对超出库存的方案给出资源缺口及成因，导出 Q4_分区配置 等结果文件。

输出：results/q4_partition_*.csv / q4_results.json
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import RES
from common.data import (load_transport_fleet, load_transport_batteries,
                         load_relay_fleet, load_relay_energy_modules)
from common.route import GTS
from common.physics import charge_time

T_TURN = {"A": 0.0, "B": 0.0, "C": 0.0}      # 运输无人机架次周转（无额外参数时为 0）


# ==================================================================== Step 1
def build_atoms(trips: pd.DataFrame):
    """按"同架次多服务区必须同组"求耦合原子。"""
    par = {}

    def find(x):
        par.setdefault(x, x)
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb

    # 先让每个服务区各自成元，保证只被单独访问的服务区也进入划分
    seen = set()
    for st in trips["stops"]:
        for x in str(st).split("->"):
            seen.add(x)
    for s in sorted(seen):
        find(s)
    for st in trips["stops"]:
        ss = str(st).split("->")
        for x in ss[1:]:
            union(ss[0], x)
    groups = defaultdict(list)
    for sid in sorted(par):
        groups[find(sid)].append(sid)
    atoms = sorted((sorted(v) for v in groups.values()),
                   key=lambda v: (-len(v), v[0]))
    return atoms


def trip_atom_map(trips: pd.DataFrame, atoms):
    """架次 -> 原子下标（架次内所有服务区同属一个原子）。"""
    sid2atom = {}
    for ai, at in enumerate(atoms):
        for s in at:
            sid2atom[s] = ai
    out = {}
    for _, r in trips.iterrows():
        a = sid2atom[str(r["stops"]).split("->")[0]]
        out[r["trip_id"]] = a
    return out


def stirling2(n: int, k: int) -> int:
    """第二类斯特林数：n 个带标号元素划入 k 个非空无标号组的方案数。"""
    if k > n or k == 0:
        return 0
    return sum((-1) ** i * math.comb(k, i) * (k - i) ** n
               for i in range(k)) // math.factorial(k)


# ==================================================================== Step 2
def legal_partitions(n_atoms: int, k: int):
    """把 n_atoms 个原子分成 k 个非空组的全部合法划分（组不带标号）。

    枚举 range(k)^n 的指派并剔除有空组的指派后，同一划分会因组的标号置换
    重复出现 k! 次，故用 seen 集合按规范化（组内升序、组间按首元素升序）
    去重，保证每个划分恰好产出一次。
    """
    seen = set()
    n = 0
    for assign in itertools.product(range(k), repeat=n_atoms):
        if len(set(assign)) != k:
            continue
        buckets = [[] for _ in range(k)]
        for a, g in zip(range(n_atoms), assign):
            buckets[g].append(a)
        groups = tuple(sorted((tuple(sorted(g)) for g in buckets),
                              key=lambda g: g[0]))
        if groups in seen:
            continue
        seen.add(groups)
        n += 1
        yield groups
    assert n == stirling2(n_atoms, k), "合法划分数与第二类斯特林数不符"


# ==================================================================== Step 3
def min_machines(intervals):
    """固定区间集合的最少机器数 = 最大并发数（区间图着色，扫描线）。

    区间按半开 [s, e) 处理：同一时刻的结束事件先于开始事件结算，
    这样"上一架次刚返回、下一架次立即起飞"由同一台机器承担时不会被
    误计为两台并发。
    """
    ev = []
    for s, e in intervals:
        ev.append((s, 1))
        ev.append((e, -1))
    ev.sort(key=lambda z: (z[0], z[1]))      # 同刻先 -1（释放）后 +1（占用）
    cur = mx = 0
    for _, d in ev:
        cur += d
        mx = max(mx, cur)
    return mx


def min_energy_resources(jobs, t_full):
    """含充电周转的能源资源最少数量。

    jobs: [(start, end, soc_end)]；资源在 end 后需 t_chg(soc_end) 充至满。
    按开始时刻贪心分配"最早可用"的资源；不足时新增一个。
    """
    ready = []                     # 各资源的最早可用时刻
    for s, e, soc in sorted(jobs, key=lambda z: z[0]):
        pick = -1
        for i, r in enumerate(ready):
            if r <= s + 1e-9 and (pick < 0 or r < ready[pick]):
                pick = i
        if pick < 0:
            ready.append(e + charge_time(t_full, soc))
        else:
            ready[pick] = e + charge_time(t_full, soc)
    return len(ready)


def group_resources(g_trips, g_relays, batt_conf, mod_conf, relay_euse):
    """单个任务组独立执行时的四类资源需求。"""
    # --- 运输无人机：按机型的并发架次数
    drone_need = {}
    for g in ("A", "B", "C"):
        iv = [(r["start"], r["end"] + T_TURN[g])
              for _, r in g_trips.iterrows() if r["gtype"] == g]
        if iv:
            drone_need[g] = min_machines(iv)
    # --- 共享电池：按机型，含充电周转
    batt_need = {}
    for g in ("A", "B", "C"):
        jobs = [(r["start"], r["end"], r["soc_end"] / 100.0)
                for _, r in g_trips.iterrows() if r["gtype"] == g]
        if jobs:
            batt_need[g] = min_energy_resources(jobs, batt_conf[g]["t_full"])
    # --- 中继无人机 / 能源组件
    relay_need = mod_need = 0
    if g_relays:
        relay_need = min_machines([(r["t_begin"], r["t_return"]) for r in g_relays])
        mod_need = min_energy_resources(
            [(r["t_begin"], r["t_return"], 1.0 - r["e_relay"] / relay_euse)
             for r in g_relays], mod_conf["t_full"])
    return dict(drones=drone_need, batteries=batt_need,
                relay_drones=relay_need, relay_modules=mod_need)


# ==================================================================== Step 4
def entropy_topsis(mat: np.ndarray, benefit: list[bool]):
    """熵权法确定权重 + TOPSIS 贴近度（benefit[i]=True 表示该列越大越好）。"""
    X = np.asarray(mat, dtype=float)
    n, m = X.shape
    # 极差标准化到 [0,1]，并统一为"越大越好"
    Z = np.zeros_like(X)
    for j in range(m):
        lo, hi = X[:, j].min(), X[:, j].max()
        if hi - lo < 1e-12:
            Z[:, j] = 1.0
        elif benefit[j]:
            Z[:, j] = (X[:, j] - lo) / (hi - lo)
        else:
            Z[:, j] = (hi - X[:, j]) / (hi - lo)
    # 熵权
    P = Z / np.maximum(Z.sum(axis=0, keepdims=True), 1e-12)
    with np.errstate(divide="ignore", invalid="ignore"):
        E = -np.nansum(np.where(P > 0, P * np.log(P), 0.0), axis=0) / np.log(n)
    d = 1.0 - E
    w = d / d.sum() if d.sum() > 1e-12 else np.full(m, 1.0 / m)
    # TOPSIS（对"越大越好"矩阵）
    V = Z * w
    best, worst = V.max(axis=0), V.min(axis=0)
    dp = np.linalg.norm(V - best, axis=1)
    dn = np.linalg.norm(V - worst, axis=1)
    score = dn / np.maximum(dp + dn, 1e-12)
    return score, w


TRANSPORT_FLEET = load_transport_fleet()
BATT_CONF = load_transport_batteries()
RELAY_FLEET = load_relay_fleet()
MOD_CONF = load_relay_energy_modules()
INV = dict(
    drones={g: int((TRANSPORT_FLEET["gtype"] == g).sum()) for g in ("A", "B", "C")},
    batteries={g: int(BATT_CONF[g]["n"]) for g in ("A", "B", "C")},
    relay_drones=int(len(RELAY_FLEET)),
    relay_modules=int(MOD_CONF["n"]),
)
RELAY_EUSE = None      # 由 q3 结果在 main 中填充


def main():
    global RELAY_EUSE
    from common.data import load_relay_type
    rt = load_relay_type()
    RELAY_EUSE = rt["Euse"]

    trips = pd.read_csv(RES / "q2_transport_trips.csv")
    relays = pd.read_csv(RES / "q3_relay_trips.csv")

    # 中继架次 -> 覆盖的中断区间 -> 所属运输架次
    oseg = pd.read_csv(RES / "q3_outage_segments.csv")
    rel2trips = defaultdict(set)
    for _, r in relays.iterrows():
        rid = r["中继架次编号"]
        # 通过中断明细反查该中继架次承担的中断所对应的运输架次
    # 中断明细里已记录 relay_trip_id 与 trip_id
    oseg["relay_trip_id"] = oseg["relay_trip_id"].fillna("")
    for _, o in oseg.iterrows():
        if o["relay_trip_id"]:
            rel2trips[o["relay_trip_id"]].add(o["trip_id"])

    atoms = build_atoms(trips)
    t2a = trip_atom_map(trips, atoms)
    print("服务区耦合原子 %d 个：" % len(atoms))
    for i, a in enumerate(atoms):
        print("  原子%d：%s（%d 个服务区）" % (i + 1, ",".join(a), len(a)))

    # 中继架次 -> 所属原子集合（其保障的运输架次所在原子）
    relay_rows = []
    for _, r in relays.iterrows():
        rid = r["中继架次编号"]
        ats = sorted({t2a[t] for t in rel2trips.get(rid, set()) if t in t2a})
        relay_rows.append(dict(rid=rid, atoms=ats,
                               t_begin=float(r["开始时刻（s）"]),
                               t_return=float(r["返回O01时刻（s）"]),
                               e_relay=float(r["架次能耗（kWh）"])))
    dfr = pd.DataFrame(relay_rows)
    print("中继架次 %d 个；原子归属 %s" %
          (len(dfr), dfr["atoms"].tolist()))

    # 自检：把全部服务区当成一个任务组时，独立核算的资源需求应与问题二/三
    # 实际投入的资源一致，用以校验资源核算模型的正确性。
    all_df = trips.copy()
    all_rl = [dict(r) for _, r in dfr.iterrows()]
    chk = group_resources(all_df, all_rl, BATT_CONF, MOD_CONF, RELAY_EUSE)
    act_dr = {g: int(trips[trips["gtype"] == g]["drone"].nunique())
              for g in ("A", "B", "C")}
    act_bt = {g: int(trips[trips["gtype"] == g]["battery"].nunique())
              for g in ("A", "B", "C")}
    print("资源核算自检（全部服务区合并为一组）")
    print("  运输无人机 需 %s / 实际 %s" % (chk["drones"], act_dr))
    print("  共享电池   需 %s / 实际 %s" % (chk["batteries"], act_bt))
    print("  中继无人机 需 %d；中继能源组件 需 %d" %
          (chk["relay_drones"], chk["relay_modules"]))
    ok = all(chk["drones"].get(g, 0) <= act_dr[g] for g in "ABC") and \
        all(chk["batteries"].get(g, 0) <= act_bt[g] for g in "ABC")
    print("  自检：%s" % ("通过（需求不超过实际投入）" if ok else "不通过"))
    # K=1（不分区的整体执行）作为对照基线
    base_scale = (sum(chk["drones"].values()) + sum(chk["batteries"].values())
                  + chk["relay_drones"] + chk["relay_modules"])
    base_gap = (sum(max(0, chk["drones"].get(g, 0) - INV["drones"][g]) for g in "ABC")
                + sum(max(0, chk["batteries"].get(g, 0) - INV["batteries"][g])
                      for g in "ABC")
                + max(0, chk["relay_drones"] - INV["relay_drones"])
                + max(0, chk["relay_modules"] - INV["relay_modules"]))
    baseline = dict(k=1, scale=base_scale, gap=base_gap,
                    drones=chk["drones"], batteries=chk["batteries"],
                    relay_drones=chk["relay_drones"],
                    relay_modules=chk["relay_modules"])
    print("  整体执行（K=1）对照基线：配置规模 %d，资源缺口 %d" %
          (base_scale, base_gap))

    all_recs = []
    for k in (2, 3):
        parts = list(legal_partitions(len(atoms), k))
        print("\n===== 划分为 %d 个任务组：合法划分 %d 个 =====" % (k, len(parts)))
        for pi, grp in enumerate(parts, 1):
            rec = dict(k=k, part_id=pi,
                       groups=" | ".join(
                           "组%d{%s}" % (gi, ",".join(
                               s for a in g for s in atoms[a]))
                           for gi, g in enumerate(grp, 1)),
                       n_areas=";".join(str(sum(len(atoms[a]) for a in g))
                                        for g in grp))
            res = []
            for g in grp:
                gset = set(g)
                gt = trips[trips["trip_id"].map(t2a).isin(gset)]
                gr = [r for _, r in dfr.iterrows()
                      if set(r["atoms"]) & gset]
                res.append(group_resources(gt, gr, BATT_CONF, MOD_CONF,
                                           RELAY_EUSE))
            # 汇总
            for cat, key in (("drones", "运输无人机"), ("batteries", "共享电池")):
                for g in ("A", "B", "C"):
                    rec[f"{key}-{g}"] = sum(r[cat].get(g, 0) for r in res)
            rec["中继无人机"] = sum(r["relay_drones"] for r in res)
            rec["中继能源组件"] = sum(r["relay_modules"] for r in res)
            # 缺口
            gap = 0
            for g in ("A", "B", "C"):
                gap += max(0, rec[f"运输无人机-{g}"] - INV["drones"][g])
                gap += max(0, rec[f"共享电池-{g}"] - INV["batteries"][g])
            gap += max(0, rec["中继无人机"] - INV["relay_drones"])
            gap += max(0, rec["中继能源组件"] - INV["relay_modules"])
            rec["资源缺口"] = gap
            # 组间工作量（以架次飞行能耗度量）
            wl = []
            for g in grp:
                gset = set(g)
                gt = trips[trips["trip_id"].map(t2a).isin(gset)]
                e = float(gt["energy"].sum())
                for _, r in dfr.iterrows():
                    if set(r["atoms"]) & gset:
                        e += float(r["e_relay"])
                wl.append(e)
            rec["组间不均衡"] = float(np.std(wl) / max(np.mean(wl), 1e-9))
            rec["各组工作量"] = ";".join("%.2f" % x for x in wl)
            rec["_wl"] = wl
            rec["_res"] = res
            rec["_grp"] = grp
            all_recs.append(rec)
            print("  划分%d %-28s 运输机 A%d/B%d/C%d 电池 A%d/B%d/C%d "
                  "中继机%d 组件%d 缺口%d 不均衡%.3f"
                  % (pi, rec["groups"],
                     rec["运输无人机-A"], rec["运输无人机-B"], rec["运输无人机-C"],
                     rec["共享电池-A"], rec["共享电池-B"], rec["共享电池-C"],
                     rec["中继无人机"], rec["中继能源组件"],
                     rec["资源缺口"], rec["组间不均衡"]))

    df = pd.DataFrame(all_recs)
    # 配置规模：绝对件数（用于报表）与按库存归一化的规模指数（用于评价，
    # 避免"1 架运输机 = 1 个能源组件"这类不同量纲资源直接相加）
    df["配置规模"] = (df[[f"运输无人机-{g}" for g in "ABC"]].sum(axis=1)
                  + df[[f"共享电池-{g}" for g in "ABC"]].sum(axis=1)
                  + df["中继无人机"] + df["中继能源组件"])
    scale_idx = np.zeros(len(df))
    for g in "ABC":
        scale_idx += df[f"运输无人机-{g}"].to_numpy(float) / INV["drones"][g]
        scale_idx += df[f"共享电池-{g}"].to_numpy(float) / INV["batteries"][g]
    scale_idx += df["中继无人机"].to_numpy(float) / INV["relay_drones"]
    scale_idx += df["中继能源组件"].to_numpy(float) / INV["relay_modules"]
    df["规模指数"] = scale_idx
    # 资源冗余 = 库存中未被该方案占用（含未动用与多组重复配置之外）的富余量，
    # 逐类取 库存 - 需求 并截断到非负，再求和。
    red = np.zeros(len(df))
    for g in "ABC":
        red += np.clip(INV["drones"][g] - df[f"运输无人机-{g}"].to_numpy(float), 0, None)
        red += np.clip(INV["batteries"][g] - df[f"共享电池-{g}"].to_numpy(float), 0, None)
    red += np.clip(INV["relay_drones"] - df["中继无人机"].to_numpy(float), 0, None)
    red += np.clip(INV["relay_modules"] - df["中继能源组件"].to_numpy(float), 0, None)
    df["冗余"] = red.astype(int)

    df.to_csv(RES / "q4_partition_all.csv", index=False, encoding="utf-8-sig")

    # 分 k 做熵权-TOPSIS。三项准则彼此独立：规模指数（归一化后的资源占用）、
    # 库存缺口（按类截断后求和）、组间不均衡（工作量变异系数）。三者均为成本型。
    # "资源冗余"与规模、缺口高度共线（冗余 ≈ 库存 - 占用），故不再入模，
    # 仅作为报表列与对比维度呈现。
    summary = []
    for k in (2, 3):
        sub = df[df["k"] == k].reset_index(drop=True)
        M = sub[["规模指数", "资源缺口", "组间不均衡"]].to_numpy(float)
        score, w = entropy_topsis(M, benefit=[False, False, False])
        sub["TOPSIS得分"] = score
        sub["排名"] = sub["TOPSIS得分"].rank(ascending=False).astype(int)
        print("\n划分 %d 组：熵权 w = 规模%.3f 缺口%.3f 不均衡%.3f" % (k, *w))
        for _, r in sub.sort_values("TOPSIS得分", ascending=False).iterrows():
            print("  #%d %s\n      规模%d(指数%.2f) 缺口%d 不均衡%.3f 冗余%d 得分%.4f"
                  % (r["排名"], r["groups"], r["配置规模"], r["规模指数"],
                     r["资源缺口"], r["组间不均衡"], r["冗余"], r["TOPSIS得分"]))
        best = sub.loc[sub["TOPSIS得分"].idxmax()]
        summary.append(dict(k=k, best_partition=best["groups"],
                            score=float(best["TOPSIS得分"]),
                            scale=int(best["配置规模"]),
                            gap=int(best["资源缺口"]),
                            imbalance=float(best["组间不均衡"]),
                            redundancy=int(best["冗余"])))
    # ---------------- 结果导出（按结果提交模板 Q4_分区配置 的表头）
    cfg_rows, gap_rows, detail_rows = [], [], []
    for s in summary:
        k = s["k"]
        rec = next(r for r in all_recs if r["k"] == k and r["groups"] == s["best_partition"])
        for gi, (grp, res) in enumerate(zip(rec["_grp"], rec["_res"]), 1):
            areas = [x for a in grp for x in atoms[a]]
            cfg_rows.append({
                "K（2或3）": k, "任务组编号": f"G{gi}",
                "服务区列表": "、".join(areas),
                "A型运输无人机数": res["drones"].get("A", 0),
                "B型运输无人机数": res["drones"].get("B", 0),
                "C型运输无人机数": res["drones"].get("C", 0),
                "A型电池组数": res["batteries"].get("A", 0),
                "B型电池组数": res["batteries"].get("B", 0),
                "C型电池组数": res["batteries"].get("C", 0),
                "中继无人机数": res["relay_drones"],
                "中继能源组件数": res["relay_modules"]})
            detail_rows.append(dict(
                K=k, 任务组=f"G{gi}", 服务区数=len(areas),
                服务区列表="、".join(areas),
                运输架次数=int(trips["trip_id"].map(t2a).isin(set(grp)).sum()),
                运输能耗kWh=round(float(
                    trips[trips["trip_id"].map(t2a).isin(set(grp))]["energy"].sum()), 4),
                工作量kWh=round(float(rec["_wl"][gi - 1]), 4)))
        # 缺口按类分解
        need = dict(
            **{f"A型运输无人机": rec["运输无人机-A"], "B型运输无人机": rec["运输无人机-B"],
               "C型运输无人机": rec["运输无人机-C"],
               "A型电池组": rec["共享电池-A"], "B型电池组": rec["共享电池-B"],
               "C型电池组": rec["共享电池-C"],
               "中继无人机": rec["中继无人机"], "中继能源组件": rec["中继能源组件"]})
        inv = {"A型运输无人机": INV["drones"]["A"], "B型运输无人机": INV["drones"]["B"],
               "C型运输无人机": INV["drones"]["C"],
               "A型电池组": INV["batteries"]["A"], "B型电池组": INV["batteries"]["B"],
               "C型电池组": INV["batteries"]["C"],
               "中继无人机": INV["relay_drones"],
               "中继能源组件": INV["relay_modules"]}
        for cat in need:
            gap_rows.append(dict(K=k, 资源类别=cat, 需求量=need[cat],
                                 库存量=inv[cat],
                                 缺口=max(0, need[cat] - inv[cat]),
                                 冗余=max(0, inv[cat] - need[cat])))
    pd.DataFrame(cfg_rows).to_csv(RES / "q4_config.csv", index=False,
                                  encoding="utf-8-sig")
    pd.DataFrame(gap_rows).to_csv(RES / "q4_gap.csv", index=False,
                                  encoding="utf-8-sig")
    pd.DataFrame(detail_rows).to_csv(RES / "q4_group_detail.csv", index=False,
                                     encoding="utf-8-sig")
    print("\n缺口分解：")
    print(pd.DataFrame(gap_rows).to_string(index=False))

    with open(RES / "q4_results.json", "w", encoding="utf-8") as f:
        json.dump(dict(atoms=atoms, inventory=INV, summary=summary,
                       baseline_k1=baseline,
                       n_legal_partitions={str(k): stirling2(len(atoms), k)
                                           for k in (2, 3)}),
                  f, ensure_ascii=False, indent=1)
    print("\n推荐方案：", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
