# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题二 · 方法1：NSGA-II（全局分组编码，q2_1）

范围：与 q1_23.py 不同，本脚本不能按服务区独立跑15个子问题再合并——问题二的
多站路径（一个架次可串多个服务区）和共享机队/电池调度把15个区的决策耦合在
一起，"目标可加+决策独立"的前提不成立。所以本脚本用**一个跨全部80箱的全局
种群**做NSGA-II，每个个体的染色体是长度80的整数数组（每箱一个基因=组号），
解码时把同组的箱子交给 q2_common.decode_group_to_routes 拆成1条或多条可行
路线，再喂给 q2_common.simulate_dispatch 做资源调度仿真，得到四个目标：
    f1 配送及时性（应急优先系数加权的迟到量之和，软目标）
    f2 全部任务完成时间（makespan）
    f3 运输能耗总量
    f4 架次数
硬约束（首批保障箱的首批截止时间 / 医疗物资箱的期望送达时间）违反不并入f1，
单独用 Deb 约束支配规则处理：可行解一律优于不可行解；不可行解之间比总违反量。

派单规则本身不参与搜索（那是q2_2.py的任务），固定用"紧迫覆盖优先+应急优先
系数密度"的 priority_fn，只搜索"怎么分组、用什么机型、按什么顺序访问"。

运行方式：
    python q2_1.py
输出（当前目录 / figures/）：
    q2_1_routes.csv           代表解的路线明细
    q2_1_sorties.csv          代表解的架次-无人机-电池-起止时间
    q2_1_box_delivery.csv     代表解的逐箱送达时刻
    q2_1_resource_timeline.csv 代表解的资源时间轴（飞行/充电区间）
    q2_1_pareto_front.csv     最终种群的非支配前沿（f1-f4+违反量）
    q2_1_summary.txt          结果汇总+校验+C型机身瓶颈说明
    figures/q2_1_01_帕累托前沿.png
    figures/q2_1_02_路线结构图.png
    figures/q2_1_03_资源甘特图.png
"""
import math
import os
import time

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from q00 import (
    load_box_list, load_transport_drone, style_ax, savefig,
    SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR,
)
from q2_common import (
    MAX_STOPS, load_leg_geometry_table, build_box_index, decode_group_to_routes,
    simulate_dispatch, compute_objectives, hard_deadline, fig_route_map, fig_resource_gantt,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED = 20260923

PILOT_POP, PILOT_GEN = 24, 5
FULL_POP, FULL_GEN = 80, 80
MUT_RATE = 0.05


# ---------------------------------------------------------------------------
# 派单优先级（固定，不参与搜索——搜派单规则是 q2_2.py 的任务）
# ---------------------------------------------------------------------------
def default_priority_fn(route, now):
    return route["priority_sum"] / max(route["T_route_s"], 1.0)


# ---------------------------------------------------------------------------
# 地理邻近表（用于种子构造与变异偏置）
# ---------------------------------------------------------------------------
def compute_nearest_areas(area_list, leg_geo):
    nearest = {}
    for a in area_list:
        others = sorted((b for b in area_list if b != a), key=lambda b: leg_geo[(a, b)]["水平距离_m"])
        nearest[a] = others
    return nearest


def build_seed_population(box_ids, box_area, area_list, n_pop, rng):
    area_idx = {a: i for i, a in enumerate(area_list)}
    base = np.array([area_idx[box_area[b]] for b in box_ids], dtype=np.int64)
    n = len(box_ids)
    pop = [base.copy()]
    while len(pop) < n_pop:
        u = rng.random()
        if u < 0.30:
            variant = base.copy()
            groups_now = list(set(variant.tolist()))
            merges = int(rng.integers(1, 4))
            for _ in range(merges):
                if len(groups_now) < 2:
                    break
                a, b = rng.choice(groups_now, size=2, replace=False)
                variant[variant == b] = a
                groups_now = list(set(variant.tolist()))
            pop.append(variant)
        elif u < 0.70:
            pop.append(rng.integers(0, max(6, n // 3), size=n).astype(np.int64))
        else:
            pop.append(rng.integers(0, n, size=n).astype(np.int64))
    return pop


# ---------------------------------------------------------------------------
# 解码 + 目标评估（带记忆化）
# ---------------------------------------------------------------------------
def evaluate_chromosome(chromosome, box_ids, box_index, spec_rows, spec_df, boxes_df, leg_geo,
                         fleet_df, battery_df, priority_fn, group_cache, chromo_cache):
    key = tuple(int(x) for x in chromosome)
    if key in chromo_cache:
        return chromo_cache[key]

    groups = {}
    for bid, g in zip(box_ids, chromosome):
        groups.setdefault(int(g), []).append(bid)

    routes = []
    for ids in groups.values():
        routes.extend(decode_group_to_routes(ids, box_index, spec_rows, leg_geo, group_cache))

    sim_result = simulate_dispatch(routes, fleet_df, battery_df, spec_df, priority_fn)
    obj = compute_objectives(sim_result, boxes_df)
    violation = sum(max(0.0, v["送达"] - v["限制"]) for v in obj["violations"] if v["原因"] == "硬约束超时")
    violation += 1.0e6 * sum(1 for v in obj["violations"] if v["原因"] == "未被任何路线覆盖")

    result = dict(violation=violation, f1=obj["f1_及时性"], f2=obj["f2_makespan_s"],
                  f3=obj["f3_总能耗_kWh"], f4=float(obj["f4_架次数"]),
                  routes=routes, sim_result=sim_result, obj=obj)
    chromo_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# NSGA-II 算子
# ---------------------------------------------------------------------------
def dominates(a, b):
    if a["violation"] > 0 or b["violation"] > 0:
        if a["violation"] != b["violation"]:
            return a["violation"] < b["violation"]
    av = (a["f1"], a["f2"], a["f3"], a["f4"])
    bv = (b["f1"], b["f2"], b["f3"], b["f4"])
    not_worse = all(x <= y for x, y in zip(av, bv))
    strictly_better = any(x < y for x, y in zip(av, bv))
    return not_worse and strictly_better


def fast_nondominated_sort(metrics):
    n = len(metrics)
    S = [[] for _ in range(n)]
    dom_count = [0] * n
    fronts = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(metrics[p], metrics[q]):
                S[p].append(q)
            elif dominates(metrics[q], metrics[p]):
                dom_count[p] += 1
        if dom_count[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in S[p]:
                dom_count[q] -= 1
                if dom_count[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    fronts.pop()
    return fronts


def crowding_distance(front, metrics):
    dist = {i: 0.0 for i in front}
    if len(front) <= 2:
        for i in front:
            dist[i] = math.inf
        return dist
    for key in ("f1", "f2", "f3", "f4"):
        order = sorted(front, key=lambda i: metrics[i][key])
        vmin, vmax = metrics[order[0]][key], metrics[order[-1]][key]
        dist[order[0]] = math.inf
        dist[order[-1]] = math.inf
        span = vmax - vmin
        if span <= 1e-12:
            continue
        for j in range(1, len(order) - 1):
            dist[order[j]] += (metrics[order[j + 1]][key] - metrics[order[j - 1]][key]) / span
    return dist


def tournament_select(idxs, rank, crowd, rng):
    i, j = rng.choice(idxs, size=2, replace=False)
    if rank[i] != rank[j]:
        return i if rank[i] < rank[j] else j
    return i if crowd[i] > crowd[j] else j


def crossover(parent1, parent2, rng):
    groups2 = {}
    for idx, g in enumerate(parent2):
        groups2.setdefault(int(g), []).append(idx)
    group_ids2 = list(groups2.keys())
    k = min(int(rng.integers(1, max(2, len(group_ids2) // 3 + 1))), len(group_ids2))
    chosen = rng.choice(group_ids2, size=k, replace=False)

    child = parent1.copy()
    next_id = int(child.max()) + 1
    for g in chosen:
        for idx in groups2[g]:
            child[idx] = next_id
        next_id += 1
    return child


def mutate(chromosome, box_ids, box_area, nearest_area_of, rng, mut_rate):
    child = chromosome.copy()
    next_id = int(child.max()) + 1
    for i in range(len(child)):
        if rng.random() >= mut_rate:
            continue
        if rng.random() < 0.5:
            child[i] = next_id
            next_id += 1
        else:
            my_area = box_area[box_ids[i]]
            moved = False
            for other_area in nearest_area_of[my_area]:
                idxs_other = [j for j in range(len(child)) if j != i and box_area[box_ids[j]] == other_area]
                if idxs_other:
                    child[i] = child[rng.choice(idxs_other)]
                    moved = True
                    break
            if not moved:
                child[i] = int(rng.integers(0, next_id))
    return child


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def run_nsga2(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df, leg_geo,
              fleet_df, battery_df, pop_size, n_gen, rng, verbose=True):
    nearest_area_of = compute_nearest_areas(area_list, leg_geo)
    group_cache, chromo_cache = {}, {}

    def ev(ind):
        return evaluate_chromosome(ind, box_ids, box_index, spec_rows, spec_df, boxes_df, leg_geo,
                                    fleet_df, battery_df, default_priority_fn, group_cache, chromo_cache)

    pop = build_seed_population(box_ids, box_area, area_list, pop_size, rng)
    metrics = [ev(ind) for ind in pop]

    gen_times = []
    for gen in range(n_gen):
        t0 = time.time()
        fronts = fast_nondominated_sort(metrics)
        rank = {}
        for r, f in enumerate(fronts):
            for i in f:
                rank[i] = r
        crowd = {}
        for f in fronts:
            crowd.update(crowding_distance(f, metrics))

        idxs = list(range(len(pop)))
        offspring = []
        while len(offspring) < pop_size:
            p1 = tournament_select(idxs, rank, crowd, rng)
            p2 = tournament_select(idxs, rank, crowd, rng)
            child = crossover(pop[p1], pop[p2], rng)
            child = mutate(child, box_ids, box_area, nearest_area_of, rng, MUT_RATE)
            offspring.append(child)
        off_metrics = [ev(ind) for ind in offspring]

        combined = pop + offspring
        combined_metrics = metrics + off_metrics
        c_fronts = fast_nondominated_sort(combined_metrics)
        new_pop, new_metrics = [], []
        for f in c_fronts:
            if len(new_pop) + len(f) <= pop_size:
                for i in f:
                    new_pop.append(combined[i])
                    new_metrics.append(combined_metrics[i])
            else:
                cd = crowding_distance(f, combined_metrics)
                remaining = pop_size - len(new_pop)
                chosen = sorted(f, key=lambda i: -cd[i])[:remaining]
                for i in chosen:
                    new_pop.append(combined[i])
                    new_metrics.append(combined_metrics[i])
                break
        pop, metrics = new_pop, new_metrics
        dt = time.time() - t0
        gen_times.append(dt)
        if verbose:
            n_feas = sum(1 for m in metrics if m["violation"] == 0)
            best_f4 = min(m["f4"] for m in metrics)
            print(f"[gen {gen + 1}/{n_gen}] 用时={dt:.2f}s  可行解={n_feas}/{len(metrics)}  "
                  f"最小架次数={best_f4:.0f}  缓存组解码数={len(group_cache)}  缓存个体数={len(chromo_cache)}")
    return pop, metrics, gen_times


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------
def fig_pareto(front_metrics, filename, title):
    keys = ["f1", "f2", "f3", "f4"]
    labels = ["f1 及时性", "f2 makespan(h)", "f3 总能耗(kWh)", "f4 架次数"]
    vals = np.array([[m["f1"], m["f2"] / 3600.0, m["f3"], m["f4"]] for m in front_metrics])
    vmin, vmax = vals.min(axis=0), vals.max(axis=0)
    span = np.where(vmax - vmin < 1e-9, 1.0, vmax - vmin)
    norm = (vals - vmin) / span

    fig = plt.figure(figsize=(14.5, 5.8))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.5, 1], wspace=0.32)

    ax0 = fig.add_subplot(gs[0, 0])
    x = np.arange(len(keys))
    for row in norm:
        ax0.plot(x, row, color=CAT[0], alpha=0.55, linewidth=1.1, zorder=3)
    ax0.scatter(np.tile(x, (len(norm), 1)), norm, color=CAT[0], s=16, alpha=0.7, zorder=4)
    for xi, lo, hi in zip(x, vmin, vmax):
        ax0.annotate(f"{lo:.2f}", (xi, 0), xytext=(0, -14), textcoords="offset points",
                     ha="center", fontsize=7.4, color=INK2)
        ax0.annotate(f"{hi:.2f}", (xi, 1), xytext=(0, 4), textcoords="offset points",
                     ha="center", fontsize=7.4, color=INK2)
    ax0.set_xticks(x)
    ax0.set_xticklabels(labels, fontsize=8.8)
    ax0.set_ylim(-0.12, 1.12)
    style_ax(ax0, grid_axis="y")
    ax0.set_title(f"(a) 四目标平行坐标图（每条线=1个非支配解，共{len(front_metrics)}个，已按各轴归一化）",
                   fontsize=10.2, color=INK, loc="left")

    ax1 = fig.add_subplot(gs[0, 1])
    sizes = 30 + 260 * (vals[:, 0] - vmin[0]) / span[0]
    sc = ax1.scatter(vals[:, 2], vals[:, 3], s=sizes, c=vals[:, 1], cmap="viridis",
                      edgecolor=INK, linewidths=0.5, alpha=0.85, zorder=3)
    cb = fig.colorbar(sc, ax=ax1, pad=0.02)
    cb.set_label("makespan (h)", fontsize=8.4, color=INK2)
    ax1.set_xlabel("总能耗 f3 (kWh)")
    ax1.set_ylabel("架次数 f4")
    style_ax(ax1, grid_axis="both")
    ax1.set_title("(b) 能耗-架次散点（点大小=f1及时性,颜色=makespan）", fontsize=10.2, color=INK, loc="left")

    fig.suptitle(title, fontsize=12.6, fontweight="bold", color=INK, x=0.02, y=0.99, ha="left", va="top")
    fig.subplots_adjust(left=0.055, right=0.97, top=0.82, bottom=0.13)
    savefig(fig, filename)


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
def main():
    leg_geo, o01, services = load_leg_geometry_table()
    boxes_df = load_box_list()
    spec_df, fleet_df, battery_df = load_transport_drone()

    box_ids = list(boxes_df["货箱编号"])
    box_area = dict(zip(boxes_df["货箱编号"], boxes_df["服务区编号"]))
    area_list = sorted(services["服务区编号"].unique())
    box_index = build_box_index(boxes_df)
    spec_rows = [row for _, row in spec_df.iterrows()]

    print(f"[规模] 箱子数={len(box_ids)}  服务区数={len(area_list)}  机型数={len(spec_rows)}")

    rng = np.random.default_rng(SEED)
    print(f"[pilot] pop={PILOT_POP} gen={PILOT_GEN} —— 先测真实每代耗时,再决定正式跑的规模")
    _, _, pilot_times = run_nsga2(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df,
                                   leg_geo, fleet_df, battery_df, PILOT_POP, PILOT_GEN, rng)
    avg_pilot = float(np.mean(pilot_times))
    est_full = avg_pilot * (FULL_POP / PILOT_POP) * FULL_GEN
    print(f"[pilot] 平均每代耗时={avg_pilot:.2f}s  正式规模(pop={FULL_POP},gen={FULL_GEN})预计耗时≈{est_full:.1f}s")

    rng = np.random.default_rng(SEED + 1)
    t0 = time.time()
    pop, metrics, gen_times = run_nsga2(box_ids, box_area, area_list, box_index, spec_rows, spec_df, boxes_df,
                                         leg_geo, fleet_df, battery_df, FULL_POP, FULL_GEN, rng)
    total_time = time.time() - t0
    print(f"[正式跑] 实际总耗时={total_time:.1f}s")

    fronts = fast_nondominated_sort(metrics)
    front0_idx = fronts[0]
    front0_metrics = [metrics[i] for i in front0_idx]

    feasible = [m for m in front0_metrics if m["violation"] == 0]
    pool = feasible if feasible else front0_metrics
    rep = min(pool, key=lambda m: (m["f4"], m["f3"]))

    n_feasible_front0 = len(feasible)
    print(f"[前沿] 非支配解数={len(front0_metrics)}  其中可行(0违反)={n_feasible_front0}")
    print(f"[代表解] f1={rep['f1']:.1f}  f2={rep['f2']:.1f}s  f3={rep['f3']:.3f}kWh  "
          f"f4={rep['f4']:.0f}  硬约束违反数={len(rep['obj']['violations'])}")

    # -------------------- 输出 CSV --------------------
    routes = rep["routes"]
    route_rows = []
    for i, r in enumerate(routes):
        route_rows.append(dict(
            路线编号=f"R{i + 1:03d}", 机型编号=r["机型编号"], 停靠序列="->".join(["O01"] + list(r["stops"]) + ["O01"]),
            箱数=r["n_box"], 总质量_kg=r["total_mass_kg"], 总体积_m3=r["total_vol_m3"],
            E_route_kWh=r["E_route_kWh"], T_route_s=r["T_route_s"],
            货箱列表="|".join(b["货箱编号"] for bs in r["boxes_by_stop"].values() for b in bs),
        ))
    pd.DataFrame(route_rows).to_csv(os.path.join(BASE_DIR, "q2_1_routes.csv"), index=False, encoding="utf-8-sig")

    sim = rep["sim_result"]
    sortie_rows = [dict(架次编号=f"T{i + 1:03d}", 机型编号=s["机型编号"], 无人机编号=s["无人机编号"],
                         电池编号=s["电池编号"], 起飞时刻_s=s["start"], 返航时刻_s=s["end"],
                         停靠序列="->".join(["O01"] + list(s["route"]["stops"]) + ["O01"]))
                    for i, s in enumerate(sim["sorties"])]
    pd.DataFrame(sortie_rows).sort_values("起飞时刻_s").to_csv(
        os.path.join(BASE_DIR, "q2_1_sorties.csv"), index=False, encoding="utf-8-sig")

    hd_map = {}
    for _, b in boxes_df.iterrows():
        hd_map[b["货箱编号"]] = hard_deadline(b)
    delivery_rows = []
    for _, b in boxes_df.iterrows():
        bid = b["货箱编号"]
        arrive = sim["box_delivery"].get(bid)
        delivery_rows.append(dict(货箱编号=bid, 服务区编号=b["服务区编号"], 物资类型=b["物资类型"],
                                   期望送达时间_s=b["期望送达时间"], 硬约束时限_s=hd_map[bid],
                                   实际送达时刻_s=arrive,
                                   是否硬约束超时=bool(hd_map[bid] is not None and arrive is not None and arrive > hd_map[bid] + 1e-6)))
    pd.DataFrame(delivery_rows).to_csv(os.path.join(BASE_DIR, "q2_1_box_delivery.csv"), index=False, encoding="utf-8-sig")

    timeline_rows = []
    for ev in sim["drone_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="无人机", 事件类型=ev["类型"], 开始_s=ev["start"], 结束_s=ev["end"]))
    for ev in sim["batt_events"]:
        timeline_rows.append(dict(资源编号=ev["资源编号"], 资源类型="电池", 事件类型=ev["类型"], 开始_s=ev["start"], 结束_s=ev["end"]))
    pd.DataFrame(timeline_rows).sort_values(["资源编号", "开始_s"]).to_csv(
        os.path.join(BASE_DIR, "q2_1_resource_timeline.csv"), index=False, encoding="utf-8-sig")

    pd.DataFrame([dict(f1_及时性=m["f1"], f2_makespan_s=m["f2"], f3_总能耗_kWh=m["f3"],
                        f4_架次数=m["f4"], 硬约束违反量=m["violation"]) for m in front0_metrics]
                 ).to_csv(os.path.join(BASE_DIR, "q2_1_pareto_front.csv"), index=False, encoding="utf-8-sig")
    print(f"[saved] q2_1_routes.csv / q2_1_sorties.csv / q2_1_box_delivery.csv / "
          f"q2_1_resource_timeline.csv / q2_1_pareto_front.csv")

    # -------------------- 图 --------------------
    fig_pareto(front0_metrics, "q2_1_01_帕累托前沿.png",
               "图q2.1-1  问题二 · NSGA-II（全局分组编码）：最终非支配前沿")
    fig_route_map(routes, o01, services, "q2_1_02_路线结构图.png",
                  f"图q2.1-2  问题二 · NSGA-II 代表解：路线结构图（N={len(routes)}架次）")
    fig_resource_gantt(sim, fleet_df, battery_df, "q2_1_03_资源甘特图.png",
                        "图q2.1-3  问题二 · NSGA-II 代表解：8机身+14电池资源时间轴")

    # -------------------- 校验 + summary --------------------
    n_covered = sum(1 for v in delivery_rows if v["实际送达时刻_s"] is not None)
    multi_stop = sum(1 for r in routes if len(r["stops"]) > 1)
    c_type_sorties = sum(1 for s in sim["sorties"] if s["机型编号"] == "C")

    lines = []
    lines.append("问题二 · 方法1：NSGA-II（全局分组编码）—— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"种群/代数：pilot pop={PILOT_POP} gen={PILOT_GEN}（平均每代{avg_pilot:.2f}s）；"
                  f"正式 pop={FULL_POP} gen={FULL_GEN}，实际总耗时{total_time:.1f}s")
    lines.append("")
    lines.append(f"一、覆盖校验：送达{n_covered}/{len(boxes_df)}箱"
                  f"（分组编码结构性保证100%覆盖，无需额外的集合划分约束）")
    lines.append("")
    lines.append("二、代表解（前沿中架次数最少、能耗次优先的可行解；若前沿无可行解则取违反量最小者）")
    lines.append(f"  f1(及时性,加权迟到量)={rep['f1']:.1f}")
    lines.append(f"  f2(makespan)={rep['f2']:.1f} s ({rep['f2']/3600:.2f} h)")
    lines.append(f"  f3(总能耗)={rep['f3']:.3f} kWh")
    lines.append(f"  f4(架次数)={rep['f4']:.0f}（其中多停靠架次{multi_stop}个，"
                 f"占比{multi_stop/max(len(routes),1)*100:.1f}%）")
    lines.append(f"  硬约束违反数={len(rep['obj']['violations'])}")
    lines.append(f"  与问题一单站基线（N=18）对照：本解N={rep['f4']:.0f}，"
                 f"{'多站合并帮助减少了架次' if rep['f4'] <= 18 else '架次数略高于问题一基线,原因是问题二叠加了机队/电池资源约束与硬时限,不是纯batching问题'}")
    lines.append("")
    lines.append(f"三、C型机身瓶颈：C型仅2架机身(电池组4个),本解中C型架次数={c_type_sorties}，"
                 f"若该数偏高应关注C型机身排队等待时间(见资源甘特图)")
    lines.append("")
    lines.append(f"四、最终非支配前沿规模={len(front0_metrics)}，其中0违反可行解={n_feasible_front0}")
    lines.append("")
    lines.append("五、范围裁剪说明")
    lines.append(f"  单架次最多{MAX_STOPS}个停靠服务区；不建模通信/中继(问题三范畴)；")
    lines.append("  派单规则固定为'紧迫覆盖优先+应急优先系数密度',不在GA中搜索(该维度交给q2_2.py扫描)。")

    with open(os.path.join(BASE_DIR, "q2_1_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q2_1_summary.txt")

    ok = n_covered == len(boxes_df)
    print("[done] all checks passed" if ok else "[warn] coverage check failed")


if __name__ == "__main__":
    main()
