# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题四共享模块（q4_common）

承接 q3_2.py（贪心构造+多站合并+中继覆盖分配+派单预设扫描）的联合调度方案，
把15个服务区分成K组、每组独立配备运输无人机/共享电池/中继无人机/中继能源
组件（组间不共享/不重调配），在问题三的路线/停靠顺序/架次分配/通信保障关系
保持不变的前提下核算每种分区方案的资源配置规模。

不用q3_1.py（NSGA-II，90架次量级）作分区基准——用户已明确要求对接q3_2.py
（贪心构造，16条合并路线/29架次：运输16+中继13）。也不用此前独立存在的
p3_common/p3-1/p3-2/p4_common/p4-1/p4-2旧轨道（那套叠加在q2_1固定路线上做
纯中继覆盖，路线本身不重新优化，与q3_2"路线+中继联合优化"结构不同）。

build_q3_2_solution() 原样重放 q3_2.py main() 的步骤1-4（只读import，不修改
q3_2.py本身），只跑"均衡"预设——q3_2.py的三组预设结果完全打平，均衡是其
主方案。q3_2_sorties.csv/q3_2_relay_sorties.csv只有停靠序列字符串、没有路线
编号，且该字符串在不同路线间可能重复，CSV层面无法可靠还原架次->路线映射；
在内存里重放能直接拿到sim_result["sorties"]/["relay_sorties"]里的route=chosen
字段——与merged_routes里的路线是同一个Python对象（已读q3_common.py源码确认
其在simulate_joint_dispatch内部创建时就是同一引用），架次->路线的对应零歧义。
"""
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from q00 import load_transport_drone, load_relay_drone, style_ax, CAT, INK, SURFACE
from q1_2_common import (
    load_base_data, enumerate_candidates, solve_set_partitioning, total_metrics, validate_selection,
)
from q2_common import load_leg_geometry_table, build_box_index, charge_time
from q2_2 import baseline_cost, route_from_areas, greedy_merge_routes, priority_balanced
from q3_common import (
    load_comm_constants, gw_position, load_dem_full, build_node_positions,
    load_or_build_relay_layer, attach_relay_requirements, simulate_joint_dispatch,
    compute_objectives_joint,
)

ROOT = os.path.dirname(os.path.abspath(__file__))

# q3_2_preset_compare.csv 里"均衡"预设的精确值(未四舍五入)，重放结果必须与之逐项一致
Q3_2_CHECK = dict(
    f1=2051542.6344868941, f2=19379.38384389104, f3=67.38725543526151,
    f4=29, f4_transport=16, f4_relay=13, violations=18, n_routes=16,
)


def build_q3_2_solution(verbose=True):
    """原样重放 q3_2.py main() 的步骤1-4，只跑"均衡"预设，返回内存态完整方案。"""
    leg_geo, o01, services = load_leg_geometry_table()
    boxes_df, spec_df, qmax_lookup, geo_table = load_base_data()
    _, fleet_df, battery_df = load_transport_drone()
    relay_spec_df, relay_fleet_df, relay_stock_df = load_relay_drone()
    relay_spec_row = relay_spec_df.iloc[0]
    box_index = build_box_index(boxes_df)

    # -------- 1. 基线构造（问题一单站集合划分，同q2_2.py） --------
    candidates = enumerate_candidates(boxes_df, spec_df, geo_table, qmax_lookup)
    cost = baseline_cost(candidates, boxes_df)
    selected = candidates.iloc[solve_set_partitioning(candidates, boxes_df, cost)].reset_index(drop=True)
    N0, E0, T0 = total_metrics(selected)
    ok0, msg0 = validate_selection(selected, boxes_df)
    if not ok0:
        raise RuntimeError("问题一单站基线覆盖校验失败,不应该发生: " + msg0)

    base_routes = []
    for _, row in selected.iterrows():
        sa = row["服务区编号"]
        box_rows = [box_index[bid] for bid in row["货箱列表"]]
        r = route_from_areas([sa], {sa: box_rows}, spec_df, leg_geo)
        if r is None:
            raise RuntimeError(f"单站批次 {sa} 转换失败——问题一已保证单站可行，不应该发生")
        base_routes.append(r)

    # -------- 2. 贪心多站合并（同q2_2.py） --------
    merge_log = []
    merged_routes = greedy_merge_routes(base_routes, spec_df, leg_geo, log=merge_log)

    all_box_ids = [b["货箱编号"] for r in merged_routes for bs in r["boxes_by_stop"].values() for b in bs]
    ok_cov = len(all_box_ids) == len(boxes_df) and len(set(all_box_ids)) == len(boxes_df)
    if not ok_cov:
        raise RuntimeError("合并后箱子覆盖校验失败,不应该发生")

    # -------- 3. 通信/中继全局预计算 + 路线级需求解析 --------
    comm = load_comm_constants()
    gw_pos = gw_position(comm, o01)
    dem_arr, dem_transform, dem_bounds = load_dem_full()
    node_lonlat, node_work_elev, node_ground_elev = build_node_positions(o01, services)
    comm_profile, relay_candidates, phase_coverage = load_or_build_relay_layer(
        leg_geo, node_lonlat, node_work_elev, comm, gw_pos, dem_arr, dem_transform, dem_bounds,
        float(relay_spec_row["最大悬停离地高度"]), use_cache=True)
    attach_relay_requirements(merged_routes, leg_geo, comm_profile, phase_coverage, spec_df)

    # -------- 4. 只跑"均衡"预设（q3_2.py三组预设完全打平，均衡是其主方案） --------
    sim = simulate_joint_dispatch(merged_routes, fleet_df, battery_df, spec_df,
                                   relay_fleet_df, relay_stock_df, relay_spec_row,
                                   relay_candidates, o01, priority_balanced)
    obj = compute_objectives_joint(sim, boxes_df)

    n_covered = sum(1 for v in sim["box_delivery"].values() if v is not None)
    checks = dict(
        n_routes=len(merged_routes) == Q3_2_CHECK["n_routes"],
        coverage=n_covered == len(boxes_df),
        f1=abs(obj["f1_及时性"] - Q3_2_CHECK["f1"]) < 1e-3,
        f2=abs(obj["f2_makespan_s"] - Q3_2_CHECK["f2"]) < 1e-3,
        f3=abs(obj["f3_总能耗_kWh"] - Q3_2_CHECK["f3"]) < 1e-6,
        f4=obj["f4_架次数"] == Q3_2_CHECK["f4"],
        f4_transport=obj["f4_运输架次"] == Q3_2_CHECK["f4_transport"],
        f4_relay=obj["f4_中继架次"] == Q3_2_CHECK["f4_relay"],
        violations=len(obj["violations"]) == Q3_2_CHECK["violations"],
    )
    if verbose:
        print(f"[q4_common自检] 合并路线数={len(merged_routes)}  覆盖{n_covered}/{len(boxes_df)}箱  "
              f"f4={obj['f4_架次数']}(运输{obj['f4_运输架次']}+中继{obj['f4_中继架次']})  "
              f"f3={obj['f3_总能耗_kWh']:.5f}kWh  违反数={len(obj['violations'])}  "
              f"自检={'全部通过' if all(checks.values()) else checks}")
    if not all(checks.values()):
        raise RuntimeError(f"重放q3_2.py结果与已知基准(q3_2_preset_compare.csv)不一致，自检失败: {checks}")

    return dict(merged_routes=merged_routes, sim=sim, obj=obj, spec_df=spec_df, fleet_df=fleet_df,
                battery_df=battery_df, relay_fleet_df=relay_fleet_df, relay_stock_df=relay_stock_df,
                relay_spec_row=relay_spec_row, relay_candidates=relay_candidates,
                boxes_df=boxes_df, o01=o01, services=services)


def build_components(merged_routes, services):
    """由同一运输架次(合并路线)的停靠序列构造原子任务块(并查集)。"""
    parent = {str(x): str(x) for x in services["服务区编号"]}

    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    for r in merged_routes:
        st = list(r["stops"])
        for x in st:
            find(x)
        for a, b in zip(st[:-1], st[1:]):
            union(a, b)

    comps = defaultdict(list)
    for x in parent:
        comps[find(x)].append(x)
    comps = [sorted(v) for v in comps.values()]
    comps.sort(key=lambda x: x[0])
    comp_of = {x: i for i, c in enumerate(comps) for x in c}
    return comps, comp_of


def overlap_peak(intervals):
    """闭开区间最大重叠数，事件扫描。"""
    events = []
    for a, b in intervals:
        if a is None or b is None:
            continue
        events.append((float(a), 1))
        events.append((float(b), -1))
    events.sort(key=lambda z: (z[0], z[1]))
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    return peak


def resource_events(sim, group_of, comp_of, spec_df, battery_df, relay_spec_row, relay_stock_df):
    """按(任务组,资源key)分桶算每组独立资源池的峰值并发需求。

    忙碌区间口径(已逐行核对q3_common.simulate_joint_dispatch源码，非估算)：
      运输无人机: [start,end]；共享电池: [start,end+chg]；
      中继无人机: [depart,ground_arrive+relay_turn_s]（含架次周转时间，若漏加会低估峰值）；
      中继能源组件: [depart,ground_arrive+relay_chg]。
    """
    e_use = dict(zip(spec_df["机型编号"], spec_df["电池可用能量"]))
    t_full = dict(zip(battery_df["机型编号"], battery_df["等效完全充电时间"]))
    relay_e_use = float(relay_spec_row["能源组件可用能量"])
    relay_t_full = float(relay_stock_df["等效完全充电时间"].values[0])
    relay_turn_s = float(relay_spec_row["架次周转时间"])

    ev = defaultdict(list)
    for s in sim["sorties"]:
        r = s["route"]
        g = group_of[comp_of[r["stops"][0]]]
        typ = s["机型编号"]
        ev[(g, f"运输无人机_{typ}")].append((s["start"], s["end"]))
        soc_after = 1.0 - r["E_route_kWh"] / e_use[typ]
        chg = charge_time(soc_after, t_full[typ])
        ev[(g, f"共享电池_{typ}")].append((s["start"], s["end"] + chg))

    for rs in sim["relay_sorties"]:
        r = rs["route"]
        g = group_of[comp_of[r["stops"][0]]]
        ev[(g, "中继无人机")].append((rs["depart"], rs["ground_arrive"] + relay_turn_s))
        relay_soc_after = 1.0 - rs["E_kWh"] / relay_e_use
        relay_chg = charge_time(relay_soc_after, relay_t_full)
        ev[(g, "中继能源组件")].append((rs["depart"], rs["ground_arrive"] + relay_chg))

    return {key: overlap_peak(v) for key, v in ev.items()}


def get_inventory(fleet_df, battery_df, relay_fleet_df, relay_stock_df):
    inv = {}
    for typ, sub in fleet_df.groupby("机型编号"):
        inv[f"运输无人机_{typ}"] = int(len(sub))
    for _, x in battery_df.iterrows():
        inv[f"共享电池_{x['机型编号']}"] = int(float(x["共享电池组总数"]))
    inv["中继无人机"] = int(len(relay_fleet_df))
    inv["中继能源组件"] = int(float(relay_stock_df["共享能源组件总数"].values[0]))
    return inv


def workload(sim, group_of, comp_of):
    out = defaultdict(lambda: {"服务区": set(), "运输架次": 0, "中继架次": 0, "箱数": 0, "质量_kg": 0.0,
                                "运输能耗_kWh": 0.0, "中继能耗_kWh": 0.0, "作业时长_s": 0.0})
    for s in sim["sorties"]:
        r = s["route"]
        g = group_of[comp_of[r["stops"][0]]]
        x = out[g]
        x["服务区"].update(r["stops"])
        x["运输架次"] += 1
        x["箱数"] += r["n_box"]
        x["质量_kg"] += r["total_mass_kg"]
        x["运输能耗_kWh"] += r["E_route_kWh"]
        x["作业时长_s"] += s["end"] - s["start"]
    for rs in sim["relay_sorties"]:
        r = rs["route"]
        g = group_of[comp_of[r["stops"][0]]]
        x = out[g]
        x["中继架次"] += 1
        x["中继能耗_kWh"] += rs["E_kWh"]
        x["作业时长_s"] += rs["ground_arrive"] - rs["depart"]
    for x in out.values():
        x["服务区"] = "、".join(sorted(x["服务区"]))
    return dict(out)


def evaluate_partition(sim, assignment, k, comp_of, spec_df, fleet_df, battery_df,
                        relay_spec_row, relay_fleet_df, relay_stock_df, components):
    """给定分区assignment(长度=len(components)，取值0..k-1)打分。

    gap/redundancy先按资源key汇总所有组的需求再与库存比较——这是相对旧
    p4_common.py的修复点：旧代码用needs.get(裸key,0)查(group,key)元组键的字典，
    永远查到0，导致redundancy恒等于sum(库存)=30，不随分区变化。这里先算
    total_need_by_key[key]=sum(needs.get((g,key),0) for g in range(k))，
    再统一比较，gap/redundancy会正确随分区方案变化。
    """
    group_of = {i: int(assignment[i]) for i in range(len(components))}
    needs = resource_events(sim, group_of, comp_of, spec_df, battery_df, relay_spec_row, relay_stock_df)
    inv = get_inventory(fleet_df, battery_df, relay_fleet_df, relay_stock_df)
    all_keys = sorted(set(inv) | {key for _, key in needs})
    total_need_by_key = {key: sum(needs.get((g, key), 0) for g in range(k)) for key in all_keys}
    gap = sum(max(0, total_need_by_key[key] - inv.get(key, 0)) for key in all_keys)
    redundancy = sum(max(0, inv.get(key, 0) - total_need_by_key[key]) for key in all_keys)
    total_need = sum(needs.values())

    w = workload(sim, group_of, comp_of)
    wvals = np.array([sum([v["作业时长_s"] / 3600.0, v["运输能耗_kWh"] + v["中继能耗_kWh"], v["箱数"] * 0.1])
                       for v in w.values()])
    balance = float(np.std(wvals) / max(np.mean(wvals), 1e-9)) if len(wvals) else 0.0

    score = (gap, total_need, balance, redundancy)
    return dict(assignment=tuple(assignment), group_of=group_of, needs=needs, inventory=inv,
                total_need_by_key=total_need_by_key, gap=gap, total_need=total_need,
                balance=balance, redundancy=redundancy, score=score, workload=w)


def all_partitions(n, k):
    """生成不重复的无标签分区编码(restricted growth string)，每组至少1个块。"""
    if n <= 0:
        return
    a = [0] * n

    def rec(pos, max_label):
        if pos == n:
            if max_label == k - 1:
                yield tuple(a)
            return
        for g in range(min(max_label + 2, k)):
            a[pos] = g
            yield from rec(pos + 1, max(max_label, g))

    yield from rec(1, 0)


def normalize_label(assignment):
    """消除组编号置换，便于保存结果时组编号顺序稳定。"""
    mp = {}
    nxt = 0
    out = []
    for x in assignment:
        if x not in mp:
            mp[x] = nxt
            nxt += 1
        out.append(mp[x])
    return tuple(out)


def partition_rows(plan, components):
    rows = []
    for i, c in enumerate(components):
        rows.append({"任务组": plan["group_of"][i] + 1, "任务块编号": i + 1,
                     "块内服务区数": len(c), "服务区列表": "、".join(c)})
    return rows


def resource_rows(plan, k):
    rows = []
    need_names = {key for _, key in plan["needs"]}
    for key in sorted(set(plan["inventory"]) | need_names):
        stock = plan["inventory"].get(key, 0)
        total = plan["total_need_by_key"].get(key, 0)
        for g in range(k):
            need = plan["needs"].get((g, key), 0)
            rows.append({"任务组": g + 1, "资源": key, "组内峰值需求": need, "现有库存": stock,
                         "K组总需求": total, "资源缺口": max(0, total - stock),
                         "资源冗余": max(0, stock - total)})
    return rows


def workload_rows(plan):
    rows = []
    for g, x in sorted(plan["workload"].items()):
        rows.append({"任务组": g + 1, **x})
    return rows


def save_figures(out_dir, tag, merged_routes, o01, services, plans, components, comp_of):
    os.makedirs(out_dir, exist_ok=True)
    colors = CAT[:5]
    o01_xy = (float(o01["经度"]), float(o01["纬度"]))

    # 01 分区地图：K=2/K=3并排
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))
    for ax, (k, plan) in zip(axes, sorted(plans.items())):
        group_of = plan["group_of"]
        svc_group = {s: group_of[comp_of[s]] for s in comp_of}
        ax.scatter(*o01_xy, marker="^", s=110, color=INK, zorder=5)
        ax.text(o01_xy[0], o01_xy[1], "O01", fontsize=8, fontweight="bold", ha="right", va="top")
        for _, s in services.iterrows():
            sid = str(s["服务区编号"])
            g = svc_group.get(sid, 0)
            ax.scatter(s["经度"], s["纬度"], s=75, color=colors[g], edgecolor=INK, zorder=4)
            ax.text(s["经度"], s["纬度"], sid, fontsize=7, ha="left", va="bottom")
        for r in merged_routes:
            path = [o01_xy]
            for p in r["stops"]:
                q = services[services["服务区编号"] == p].iloc[0]
                path.append((float(q["经度"]), float(q["纬度"])))
            path.append(o01_xy)
            g = svc_group.get(r["stops"][0], 0)
            ax.plot([x[0] for x in path], [x[1] for x in path], color=colors[g], alpha=.3, lw=1.2, zorder=2)
        ax.set_title(f"{tag}：{k}组服务区分区", loc="left", fontweight="bold")
        ax.set_xlabel("经度"); ax.set_ylabel("纬度")
        style_ax(ax, "both")
        ax.legend(handles=[Patch(color=colors[i], label=f"任务组{i + 1}") for i in range(k)],
                  frameon=False, fontsize=8, loc="best")
    fig.savefig(os.path.join(out_dir, f"{tag}_01_分区地图.png"), bbox_inches="tight", facecolor=SURFACE, dpi=180)
    plt.close(fig)

    # 02 资源需求 vs 库存
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.5))
    for ax, (k, plan) in zip(axes, sorted(plans.items())):
        need_names = {key for _, key in plan["needs"]}
        keys = sorted(set(plan["inventory"]) | need_names)
        x = np.arange(len(keys))
        width = 0.78 / k
        for g in range(k):
            ax.bar(x + (g - (k - 1) / 2) * width, [plan["needs"].get((g, key), 0) for key in keys],
                   width, label=f"组{g + 1}", color=colors[g])
        ax.plot(x, [plan["inventory"].get(key, 0) for key in keys], color=INK, ls="--", marker="o", label="现有库存")
        ax.set_xticks(x); ax.set_xticklabels(keys, rotation=35, ha="right", fontsize=8)
        ax.set_ylabel("数量"); ax.set_title(f"{k}组资源需求与库存", loc="left", fontweight="bold")
        style_ax(ax, "y"); ax.legend(frameon=False, fontsize=8)
    fig.savefig(os.path.join(out_dir, f"{tag}_02_资源需求库存.png"), bbox_inches="tight", facecolor=SURFACE, dpi=180)
    plt.close(fig)

    # 03 组间工作量均衡
    fig, ax = plt.subplots(figsize=(9, 5))
    labels, vals = [], []
    for k, plan in sorted(plans.items()):
        for g, x in sorted(plan["workload"].items()):
            labels.append(f"{k}组-组{g + 1}")
            vals.append(x["作业时长_s"] / 3600 + x["运输能耗_kWh"] + x["中继能耗_kWh"] + x["箱数"] * 0.1)
    ax.bar(labels, vals, color=[colors[i % len(colors)] for i in range(len(vals))])
    ax.set_ylabel("归一化工作量"); ax.set_title(f"{tag} 任务组工作量比较", loc="left", fontweight="bold")
    ax.tick_params(axis="x", rotation=25); style_ax(ax, "y")
    fig.savefig(os.path.join(out_dir, f"{tag}_03_工作量均衡.png"), bbox_inches="tight", facecolor=SURFACE, dpi=180)
    plt.close(fig)

    # 04 资源缺口与冗余
    fig, ax = plt.subplots(figsize=(10, 5))
    labels, gaps, reds = [], [], []
    for k, plan in sorted(plans.items()):
        labels.append(f"{k}组")
        gaps.append(plan["gap"])
        reds.append(plan["redundancy"])
    x = np.arange(len(labels))
    ax.bar(x, gaps, label="资源缺口", color="#d94b4b")
    ax.bar(x, reds, bottom=gaps, label="组内冗余", color=CAT[3])
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("资源数量"); ax.set_title(f"{tag} 资源缺口与冗余", loc="left", fontweight="bold")
    style_ax(ax, "y"); ax.legend(frameon=False)
    fig.savefig(os.path.join(out_dir, f"{tag}_04_缺口冗余.png"), bbox_inches="tight", facecolor=SURFACE, dpi=180)
    plt.close(fig)
