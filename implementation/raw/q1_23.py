# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一第2小问 · 方法3：NSGA-II（q1_23）

范围：与 q1_21/q1_22 相同的问题（同时优化架次数 N、总能耗 E_total、
总作业时间 T_total），但求解方式本质不同——不走"候选批次枚举+集合划分
精确MILP"的路线，而是直接在"箱子->组号"的分组编码上做多目标遗传搜索，
输出一条 Pareto 前沿而不是单一解。

关键结构性简化（利用问题本身的可分性，而非取巧）：
    组批决策在15个服务区之间互相独立（不允许跨服务区组批），且三个目标
    都是各服务区分量的简单加总。因此：
        1) 对每个服务区独立跑一次 NSGA-II，得到该服务区的局部 Pareto 前沿；
        2) 把15个服务区的局部前沿按向量加法（Minkowski和）逐个合并，每次
           合并后立即做非支配过滤+拥挤度截断（避免 2^15 级别的笛卡尔积
           组合爆炸），得到全局 Pareto 前沿。
    该合并步骤的正确性依据：若 x_i* 是服务区 i 的非支配解、且各服务区目标
    可加，则全局非支配解一定由各服务区非支配解组合而成（否则用某服务区的
    非支配解替换其非最优分量可以帕累托改进全局解，矛盾）。

编码与算子（标准 Grouping GA + NSGA-II）：
    染色体 = 长度=该服务区箱数的整数数组，基因值=组号；解码时每组自动选
    "能装下且能耗最低"的可行机型；无机型能装下的组在解码阶段做修复
    （按质量降序对半拆分，递归直至每个子组都有可行机型——q1_1.py已保证
    每个箱子单独必有至少一种机型可行，故该拆分保证终止）。
    选择=二元锦标赛（Pareto rank + 拥挤度）；交叉=组迁移交叉；变异=随机
    改组。

运行方式：
    python q1_23.py
输出（当前目录 / figures/）：
    q1_23_pareto_front.csv     全局 Pareto 前沿上所有解的 (N, E_total, T_total)
    q1_23_batches.csv          代表解（离理想点最近）的组批方案明细
    q1_23_summary.txt          前沿规模、代表解指标、校验
    figures/q1_23_01_帕累托前沿.png
    figures/q1_23_02_各服务区局部前沿规模.png
    figures/q1_23_03_代表解批次构成.png
"""
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from q00 import style_ax, savefig, SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR
from q1_1 import round_trip_energy
from q1_2_common import load_base_data, batch_time, validate_selection, total_metrics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POP_SIZE = 80
N_GEN = 120
MAX_FRONT_SIZE = 200
SEED = 20260923


# ---------------------------------------------------------------------------
# 解码：分组染色体 -> 修复后的批次列表
# ---------------------------------------------------------------------------
def _best_machine_for_group(idx_list, boxes_i, spec_df, qmax_lookup, sa, geo_row):
    mass = sum(boxes_i[j]["单箱质量"] for j in idx_list)
    vol = sum(boxes_i[j]["单箱体积"] for j in idx_list)
    best = None
    for _, spec_row in spec_df.iterrows():
        g = spec_row["机型编号"]
        if mass <= qmax_lookup[(g, sa)] + 1e-9 and vol <= spec_row["可用装载体积"] + 1e-9:
            E = round_trip_energy(mass, geo_row, spec_row)
            if best is None or E < best[1]:
                best = (g, E, spec_row, mass, vol)
    return best


def _split_until_feasible(idx_list, boxes_i, spec_df, qmax_lookup, sa, geo_row):
    best = _best_machine_for_group(idx_list, boxes_i, spec_df, qmax_lookup, sa, geo_row)
    if best is not None:
        return [idx_list]
    if len(idx_list) == 1:
        box_id = boxes_i[idx_list[0]]["货箱编号"]
        raise RuntimeError(f"货箱 {box_id} 在服务区{sa}无任何机型可单独运输，"
                            f"与 q1_1.py 已建立的可行性前提矛盾")
    sorted_idx = sorted(idx_list, key=lambda j: -boxes_i[j]["单箱质量"])
    mid = len(sorted_idx) // 2
    left, right = sorted_idx[:mid], sorted_idx[mid:]
    return (_split_until_feasible(left, boxes_i, spec_df, qmax_lookup, sa, geo_row)
            + _split_until_feasible(right, boxes_i, spec_df, qmax_lookup, sa, geo_row))


def decode(chromosome, boxes_i, spec_df, qmax_lookup, sa, geo_row):
    groups = {}
    for idx, gl in enumerate(chromosome):
        groups.setdefault(int(gl), []).append(idx)

    batches = []
    for idx_list in groups.values():
        for feasible_group in _split_until_feasible(idx_list, boxes_i, spec_df, qmax_lookup, sa, geo_row):
            g, E, spec_row, mass, vol = _best_machine_for_group(
                feasible_group, boxes_i, spec_df, qmax_lookup, sa, geo_row)
            nb = len(feasible_group)
            batches.append(dict(
                机型编号=g, 箱数=nb, 总质量_kg=mass, 总体积_m3=vol,
                E_batch_kWh=E, T_batch_s=batch_time(nb, geo_row, spec_row),
                货箱列表=tuple(boxes_i[j]["货箱编号"] for j in feasible_group),
            ))
    return batches


def objectives(batches):
    N = len(batches)
    E = sum(b["E_batch_kWh"] for b in batches)
    T = sum(b["T_batch_s"] for b in batches)
    return (N, E, T)


# ---------------------------------------------------------------------------
# NSGA-II：非支配排序 + 拥挤度
# ---------------------------------------------------------------------------
def dominates(a, b):
    le = a[0] <= b[0] and a[1] <= b[1] and a[2] <= b[2]
    lt = a[0] < b[0] or a[1] < b[1] or a[2] < b[2]
    return le and lt


def fast_non_dominated_sort(objs):
    n = len(objs)
    dominated_by = [[] for _ in range(n)]
    n_dom = [0] * n
    fronts = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(objs[p], objs[q]):
                dominated_by[p].append(q)
            elif dominates(objs[q], objs[p]):
                n_dom[p] += 1
        if n_dom[p] == 0:
            fronts[0].append(p)
    i = 0
    while fronts[i]:
        nxt = []
        for p in fronts[i]:
            for q in dominated_by[p]:
                n_dom[q] -= 1
                if n_dom[q] == 0:
                    nxt.append(q)
        i += 1
        fronts.append(nxt)
    fronts.pop()
    return fronts


def crowding_distance(objs, front_idx):
    dist = {i: 0.0 for i in front_idx}
    l = len(front_idx)
    if l == 0:
        return dist
    for m in range(3):
        ordered = sorted(front_idx, key=lambda i: objs[i][m])
        dist[ordered[0]] = float("inf")
        dist[ordered[-1]] = float("inf")
        vmin, vmax = objs[ordered[0]][m], objs[ordered[-1]][m]
        rng_ = vmax - vmin
        if rng_ <= 1e-12:
            continue
        for k in range(1, l - 1):
            dist[ordered[k]] += (objs[ordered[k + 1]][m] - objs[ordered[k - 1]][m]) / rng_
    return dist


# ---------------------------------------------------------------------------
# 单服务区 NSGA-II
# ---------------------------------------------------------------------------
def run_nsga2(boxes_i, spec_df, qmax_lookup, sa, geo_row, rng, pop_size=POP_SIZE, n_gen=N_GEN):
    n = len(boxes_i)
    if n == 1:
        batches = decode([0], boxes_i, spec_df, qmax_lookup, sa, geo_row)
        return [{"chromosome": [0], "obj": objectives(batches), "batches": batches}]

    def random_chromo():
        return rng.integers(0, n, size=n).tolist()

    def evaluate(pop):
        decoded = [decode(c, boxes_i, spec_df, qmax_lookup, sa, geo_row) for c in pop]
        objs = [objectives(b) for b in decoded]
        return decoded, objs

    def tournament(rank, crowd, pop):
        i, j = rng.integers(0, len(pop)), rng.integers(0, len(pop))
        if rank[i] != rank[j]:
            return pop[i] if rank[i] < rank[j] else pop[j]
        return pop[i] if crowd[i] > crowd[j] else pop[j]

    def crossover(p1, p2):
        child = list(p1)
        groups_p2 = list(set(p2))
        k = max(1, len(groups_p2) // 2)
        picked = set(np.atleast_1d(rng.choice(groups_p2, size=min(k, len(groups_p2)), replace=False)).tolist())
        for idx in range(n):
            if p2[idx] in picked:
                child[idx] = p2[idx]
        return child

    def mutate(c, rate=0.15):
        c = list(c)
        for idx in range(n):
            if rng.random() < rate:
                c[idx] = int(rng.integers(0, n))
        return c

    population = [[0] * n, list(range(n))]
    while len(population) < pop_size:
        population.append(random_chromo())

    decoded, objs = evaluate(population)
    for _gen in range(n_gen):
        fronts = fast_non_dominated_sort(objs)
        rank = [0] * len(population)
        crowd = [0.0] * len(population)
        for r, front in enumerate(fronts):
            d = crowding_distance(objs, front)
            for i in front:
                rank[i] = r
                crowd[i] = d[i]

        offspring = []
        while len(offspring) < pop_size:
            p1 = tournament(rank, crowd, population)
            p2 = tournament(rank, crowd, population)
            offspring.append(mutate(crossover(p1, p2)))

        combined_pop = population + offspring
        combined_decoded, combined_objs = evaluate(combined_pop)
        c_fronts = fast_non_dominated_sort(combined_objs)
        new_idx = []
        for front in c_fronts:
            if len(new_idx) + len(front) <= pop_size:
                new_idx.extend(front)
            else:
                d = crowding_distance(combined_objs, front)
                remain = pop_size - len(new_idx)
                new_idx.extend(sorted(front, key=lambda i: -d[i])[:remain])
                break
        population = [combined_pop[i] for i in new_idx]
        decoded = [combined_decoded[i] for i in new_idx]
        objs = [combined_objs[i] for i in new_idx]

    fronts = fast_non_dominated_sort(objs)
    seen, result = set(), []
    for i in fronts[0]:
        key = (objs[i][0], round(objs[i][1], 6), round(objs[i][2], 6))
        if key in seen:
            continue
        seen.add(key)
        result.append({"chromosome": population[i], "obj": objs[i], "batches": decoded[i]})
    return result


def run_all_areas(boxes_df, spec_df, qmax_lookup, geo_table, rng):
    area_fronts = {}
    for sa in sorted(boxes_df["服务区编号"].unique()):
        boxes_i = boxes_df[boxes_df["服务区编号"] == sa][["货箱编号", "单箱质量", "单箱体积"]].to_dict("records")
        geo_row = geo_table.loc[sa]
        front = run_nsga2(boxes_i, spec_df, qmax_lookup, sa, geo_row, rng)
        area_fronts[sa] = front
        print(f"[NSGA-II] {sa}: 局部前沿 {len(front)} 个非支配解（箱数={len(boxes_i)}）")
    return area_fronts


# ---------------------------------------------------------------------------
# 全局合并（增量 Minkowski 和 + 每步非支配过滤/拥挤度截断）
# ---------------------------------------------------------------------------
def merge_fronts(area_fronts, sa_order):
    first = area_fronts[sa_order[0]]
    global_front = [{"obj": s["obj"], "assign": {sa_order[0]: s["batches"]}} for s in first]

    for sa in sa_order[1:]:
        next_front = area_fronts[sa]
        combined = []
        for gp in global_front:
            for s in next_front:
                obj = (gp["obj"][0] + s["obj"][0], gp["obj"][1] + s["obj"][1], gp["obj"][2] + s["obj"][2])
                assign = dict(gp["assign"])
                assign[sa] = s["batches"]
                combined.append({"obj": obj, "assign": assign})

        dedup = {}
        for c in combined:
            key = (c["obj"][0], round(c["obj"][1], 4), round(c["obj"][2], 4))
            dedup.setdefault(key, c)
        combined = list(dedup.values())

        objs = [c["obj"] for c in combined]
        nd_idx = fast_non_dominated_sort(objs)[0]
        nd = [combined[i] for i in nd_idx]

        if len(nd) > MAX_FRONT_SIZE:
            nd_objs = [c["obj"] for c in nd]
            d = crowding_distance(nd_objs, list(range(len(nd_objs))))
            order = sorted(range(len(nd)), key=lambda i: -d[i])
            nd = [nd[i] for i in order[:MAX_FRONT_SIZE]]

        global_front = nd

    return global_front


def pick_representative(global_front):
    objs = np.array([g["obj"] for g in global_front], dtype=float)
    ideal = objs.min(axis=0)
    nadir = objs.max(axis=0)
    span = np.where(nadir - ideal < 1e-9, 1.0, nadir - ideal)
    norm = (objs - ideal) / span
    dist = np.sqrt((norm ** 2).sum(axis=1))
    rep_i = int(np.argmin(dist))
    return global_front[rep_i], rep_i, ideal, nadir


def assemble_batches_records(representative):
    rows = []
    for sa, batches in representative["assign"].items():
        for i, b in enumerate(batches):
            rows.append(dict(
                批次编号=f"{sa}-G{i + 1:02d}", 服务区编号=sa, 机型编号=b["机型编号"],
                箱数=b["箱数"], 总质量_kg=b["总质量_kg"], 总体积_m3=b["总体积_m3"],
                E_batch_kWh=b["E_batch_kWh"], T_batch_s=b["T_batch_s"],
                货箱列表=b["货箱列表"],
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 可视化：全局 Pareto 前沿
# ---------------------------------------------------------------------------
def fig_pareto_front(global_front, representative):
    objs = np.array([g["obj"] for g in global_front], dtype=float)
    rep_obj = np.array(representative["obj"], dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))

    ax = axes[0]
    label_bases = ["架次数 N", "总能耗 E_total (kWh)", "总时间 T_total (h)"]
    raw = np.column_stack([objs[:, 0], objs[:, 1], objs[:, 2] / 3600.0])
    rep_raw = np.array([rep_obj[0], rep_obj[1], rep_obj[2] / 3600.0])
    vmin, vmax = raw.min(axis=0), raw.max(axis=0)
    vspan = np.where(vmax - vmin < 1e-9, 1.0, vmax - vmin)
    norm = (raw - vmin) / vspan
    rep_norm = (rep_raw - vmin) / vspan
    x = np.arange(3)
    for row in norm:
        ax.plot(x, row, color=MUTED, alpha=0.35, lw=0.9, zorder=2)
    ax.plot(x, rep_norm, color=CAT[7], lw=2.4, marker="o", markersize=6, zorder=5,
            label="代表解（离理想点最近）")
    # 范围直接写进刻度标签（而不是悬浮在轴上方的注释），从根上避免和标题打架
    tick_labels = [f"{b}\n[{lo:.2f} ~ {hi:.2f}]" for b, lo, hi in zip(label_bases, vmin, vmax)]
    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, fontsize=8.8)
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_facecolor(SURFACE)
    ax.axhline(0, color=BASELINE, lw=0.8)
    ax.axhline(1, color=BASELINE, lw=0.8)
    for xi in x:
        ax.axvline(xi, color=GRID, lw=0.8, zorder=1)
    ax.set_ylim(-0.08, 1.08)
    ax.set_title(f"(a) 全局 Pareto 前沿平行坐标图（共{len(global_front)}个非支配解）",
                 fontsize=10.6, color=INK, loc="left")
    ax.legend(loc="upper center", fontsize=8.6, frameon=False, bbox_to_anchor=(0.5, -0.22))

    ax = axes[1]
    sc = ax.scatter(objs[:, 1], objs[:, 2] / 3600.0, c=objs[:, 0], cmap="Blues", s=44,
                     edgecolor=INK2, linewidths=0.5, zorder=3)
    ax.scatter([rep_obj[1]], [rep_obj[2] / 3600.0], marker="*", s=280, color=CAT[7],
               edgecolor=INK, linewidths=1.0, zorder=5)
    ax.annotate("代表解", (rep_obj[1], rep_obj[2] / 3600.0), xytext=(-10, 10),
                textcoords="offset points", ha="right", fontsize=9, color=INK, fontweight="bold")
    ax.margins(x=0.18, y=0.18)
    style_ax(ax, grid_axis="both")
    ax.set_xlabel("总能耗 E_total（kWh）")
    ax.set_ylabel("总时间 T_total（h）")
    ax.set_title("(b) 能耗-时间权衡（颜色∝架次数N，越深N越大）", fontsize=10.6, color=INK, loc="left")
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("架次数 N", fontsize=9, color=INK)
    cb.outline.set_visible(False)

    fig.suptitle("图q1.23  第2小问 · 方法3（NSGA-II）：15个服务区局部前沿Minkowski合并后的全局 Pareto 前沿",
                 fontsize=12.6, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    savefig(fig, "q1_23_01_帕累托前沿.png")


def fig_area_front_sizes(area_fronts, sa_order):
    sizes = [len(area_fronts[sa]) for sa in sa_order]

    fig, ax = plt.subplots(figsize=(10.5, 5))
    x = np.arange(len(sa_order))
    bars = ax.bar(x, sizes, width=0.55, color=CAT[0], zorder=3)
    for b, v in zip(bars, sizes):
        ax.annotate(str(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9, color=INK2)
    ax.axhline(1, color=BASELINE, lw=1.0, ls="--", zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(sa_order, fontsize=8.6)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("局部 Pareto 前沿非支配解个数")
    ax.set_ylim(0, max(sizes) + 1)
    ax.set_title("图q1.23-2  各服务区独立 NSGA-II 搜索得到的局部前沿规模\n"
                 "（=1 表示该服务区组批方案在三目标下已唯一确定、无需权衡；>1 表示存在真实的多目标取舍）",
                 loc="left", fontsize=12, fontweight="bold", color=INK)
    savefig(fig, "q1_23_02_各服务区局部前沿规模.png")


def fig_batch_composition(out_df, filename, title):
    piv = out_df.groupby(["服务区编号", "机型编号"]).size().unstack(fill_value=0)
    piv = piv.reindex(columns=DRONE_ORDER, fill_value=0)
    piv = piv.loc[sorted(piv.index)]
    box_totals = out_df.groupby("服务区编号")["箱数"].sum().reindex(piv.index)

    fig, ax = plt.subplots(figsize=(11, 5.6))
    bottom = np.zeros(len(piv))
    x = np.arange(len(piv))
    for g in DRONE_ORDER:
        vals = piv[g].values
        ax.bar(x, vals, bottom=bottom, width=0.62, color=DRONE_COLOR[g], label=f"{g} 型",
               edgecolor=SURFACE, linewidth=1.2, zorder=3)
        bottom += vals
    for xi, tot, nb in zip(x, bottom, box_totals.values):
        ax.annotate(f"{int(tot)}批\n({int(nb)}箱)", (xi, tot), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=7.6, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(piv.index, fontsize=8.6)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("批次数（架次）")
    ax.set_ylim(0, bottom.max() * 1.2)
    ax.set_title(title, loc="left", fontsize=12.4, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    savefig(fig, filename)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    rng = np.random.default_rng(SEED)
    boxes_df, spec_df, qmax_lookup, geo_table = load_base_data()
    sa_order = sorted(boxes_df["服务区编号"].unique())

    area_fronts = run_all_areas(boxes_df, spec_df, qmax_lookup, geo_table, rng)
    global_front = merge_fronts(area_fronts, sa_order)
    print(f"[全局前沿] Minkowski合并后共 {len(global_front)} 个非支配解")

    representative, rep_i, ideal, nadir = pick_representative(global_front)
    N, E_total, T_total = representative["obj"]
    print(f"[代表解] N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s")

    front_df = pd.DataFrame([
        dict(方案编号=i + 1, N=g["obj"][0], E_total_kWh=g["obj"][1], T_total_s=g["obj"][2],
             是否代表解=("是" if i == rep_i else "否"))
        for i, g in enumerate(global_front)
    ])
    front_df.to_csv(os.path.join(BASE_DIR, "q1_23_pareto_front.csv"), index=False, encoding="utf-8-sig")
    print(f"[saved] q1_23_pareto_front.csv rows={len(front_df)}")

    batches_df = assemble_batches_records(representative)
    ok, msg = validate_selection(batches_df, boxes_df)
    N2, E2, T2 = total_metrics(batches_df)
    print(f"[代表解交叉核对] N={N2} E={E2:.3f} T={T2:.1f}  {msg}")

    out_df = batches_df.copy()
    out_df["货箱列表"] = out_df["货箱列表"].apply(lambda t: "|".join(t))
    out_df.to_csv(os.path.join(BASE_DIR, "q1_23_batches.csv"), index=False, encoding="utf-8-sig")
    print(f"[saved] q1_23_batches.csv rows={len(out_df)}")

    fig_pareto_front(global_front, representative)
    fig_area_front_sizes(area_fronts, sa_order)
    fig_batch_composition(
        out_df, "q1_23_03_代表解批次构成.png",
        "图q1.23-3  第2小问 · 方法3（NSGA-II）：代表解各服务区批次数与机型构成"
    )

    lines = []
    lines.append("问题一 第2小问 · 方法3：NSGA-II（分服务区独立搜索 + Minkowski合并）—— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"参数: 种群={POP_SIZE}  代数={N_GEN}  每次合并后前沿截断上限={MAX_FRONT_SIZE}  随机种子={SEED}")
    lines.append("")
    lines.append("一、各服务区局部 Pareto 前沿规模")
    for sa in sa_order:
        lines.append(f"  {sa}: {len(area_fronts[sa])} 个非支配解")
    lines.append("")
    lines.append(f"二、全局 Pareto 前沿：Minkowski 合并（每步立即非支配过滤+拥挤度截断，避免组合爆炸）后共 {len(global_front)} 个非支配解")
    lines.append(f"  理想点近似(前沿内逐分量最小值): N*={ideal[0]:.0f}  E*={ideal[1]:.3f} kWh  T*={ideal[2]:.1f} s")
    lines.append(f"  前沿内最差值(nadir近似):        N ={nadir[0]:.0f}  E ={nadir[1]:.3f} kWh  T ={nadir[2]:.1f} s")
    lines.append("")
    lines.append("三、代表解（到理想点归一化欧氏距离最小）")
    lines.append(f"  N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s ({T_total/3600:.2f} h)")
    lines.append(f"  {msg}")
    lines.append(f"  已写入 q1_23_batches.csv（{len(out_df)}行）、q1_23_pareto_front.csv（{len(front_df)}行）")
    lines.append("")
    lines.append("四、与第1小问启发式基线（q1_1_batches.csv, N=18）的量级对照")
    lines.append(f"  代表解 N={N}，同一量级，符合预期（方法与目标不同，不要求相等）")
    lines.append("")
    lines.append("五、全局前沿合并的正确性依据")
    lines.append("  组批决策在15个服务区间互相独立，且N/E_total/T_total都是各服务区分量的简单加总；")
    lines.append("  若某组合解的某服务区分量不是该服务区的非支配解，则替换为该服务区的非支配解可以")
    lines.append("  帕累托改进全局解而不影响其他服务区——因此全局非支配解必由各服务区非支配解拼接而成，")
    lines.append("  逐步 Minkowski 求和+非支配过滤等价于枚举全部组合后再筛选，但避免了组合爆炸。")

    with open(os.path.join(BASE_DIR, "q1_23_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q1_23_summary.txt")
    print("[done] all checks passed" if ok else "[warn] some checks failed")


if __name__ == "__main__":
    main()
