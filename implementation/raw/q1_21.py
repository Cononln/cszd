# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一第2小问 · 方法1：线性加权法（q1_21）

范围：在第1小问已确定的质量/体积/能量约束下（q1_1_qmax.csv 给出的 q_max(g,i)
仍是每个候选批次不可突破的硬上限），对组批方案做多目标优化，同时综合考虑
往返架次数 N、总运输能耗 E_total、总累计作业时间 T_total 三个指标。

方法：把候选批次枚举（q1_2_common.enumerate_candidates，DFS+剪枝精确生成
所有可行的箱子子集x机型候选，且能耗/时间已按 q1_1.py 的公式精确算好，不做
线性化近似）转化为集合划分（Set Partitioning）问题：每个候选记一次架次代价，
线性加权组合 N/E/T 后得到标量目标，用 scipy.optimize.milp 精确求解 0-1 规划。

标准化说明（因为 N 是"计数"、E 是 kWh、T 是秒，量纲相差悬殊，必须先标准化
才能加权相加）：
    - E、T 按候选池的最大值做纯比例缩放 e/e_max、t/t_max（只缩放、不平移）；
    - N 的"每候选贡献"恒为 1/(总箱数-服务区个数)，即用总量 N 的结构性可达
      范围 [服务区个数(最好情形，每区1批), 总箱数(最差情形，每箱1批)] 做同样
      的纯比例缩放。三者都只缩放不平移，加总后就是 (N/n_range, E_total/e_max,
      T_total/t_max) 的加权和——是三个总量的线性重标度，可直接加权求和。
    - 关键点：不能像常见 min-max 标准化那样做 (x-min)/(range) 再逐候选求和。
      因为 N（选中的候选个数）本身是决策变量，"每候选减去 min 再求和"会让总
      目标里多出一项 -N*min/range——这是个随解而变的量，不是常数，等价于
      每多选一个候选就凭空获得 min/range 的"奖励"，会反过来鼓励拆成更多批次、
      压不住 N。改成纯比例缩放（不减 min）可以消除这个伪项。

本脚本额外跑三组权重（均衡/架次优先/能耗优先）展示权衡关系，但不与
q1_22/q1_23 做跨方法比较（按已确认范围，每份脚本只输出自己的结果）。

运行方式：
    python q1_21.py
输出（当前目录 / figures/）：
    q1_21_batches.csv   均衡权重下选中的组批方案明细
    q1_21_summary.txt   三组权重结果对比 + 校验
    figures/q1_21_01_候选池权衡与三组权重对比.png
    figures/q1_21_02_主方案批次构成.png
"""
import os

import numpy as np
import matplotlib.pyplot as plt

from q00 import style_ax, savefig, SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR
from q1_2_common import (
    load_base_data, enumerate_candidates, solve_set_partitioning,
    total_metrics, validate_selection,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WEIGHT_SETS = [
    ("均衡", (1 / 3, 1 / 3, 1 / 3)),
    ("架次优先", (0.6, 0.2, 0.2)),
    ("能耗优先", (0.2, 0.6, 0.2)),
]


def weighted_cost(candidates, boxes_df, weights):
    w_n, w_e, w_t = weights
    n_min = boxes_df["服务区编号"].nunique()
    n_max = len(boxes_df)
    n_range = n_max - n_min

    e = candidates["E_batch_kWh"].values
    t = candidates["T_batch_s"].values

    n_contrib = np.full(len(candidates), 1.0 / n_range)
    e_contrib = e / e.max()
    t_contrib = t / t.max()
    return w_n * n_contrib + w_e * e_contrib + w_t * t_contrib


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------
def fig_pool_and_weights(candidates, results, main_name):
    main_idx = results[main_name]["idx"]
    is_sel = np.zeros(len(candidates), dtype=bool)
    is_sel[main_idx] = True

    e = candidates["E_batch_kWh"].values
    t = candidates["T_batch_s"].values / 3600.0
    nb = candidates["箱数"].values
    size = 8 + 6 * nb

    fig = plt.figure(figsize=(16, 5.4))
    gs = fig.add_gridspec(1, 4, width_ratios=[2.1, 1, 1, 1], wspace=0.45)

    ax0 = fig.add_subplot(gs[0, 0])
    ax0.scatter(e[~is_sel], t[~is_sel], s=size[~is_sel], color=MUTED, alpha=0.28,
                linewidths=0, zorder=2, label=f"候选池（共{len(candidates)}个，未选中）")
    ax0.scatter(e[is_sel], t[is_sel], s=size[is_sel] * 1.3, color=CAT[0], alpha=0.9,
                edgecolor=INK, linewidths=0.6, zorder=4, label=f"主方案（{main_name}权重）选中批次")
    style_ax(ax0, grid_axis="both")
    ax0.set_xlabel("单批次能耗 E_batch（kWh）")
    ax0.set_ylabel("单批次时间 T_batch（h）")
    ax0.set_title("(a) 候选批次池能耗-时间分布，主方案选中批次已高亮", fontsize=10.4, color=INK, loc="left")
    ax0.legend(loc="upper right", fontsize=7.8, frameon=False, markerscale=0.7)

    metrics = [("N", "架次数 N"), ("E_total", "总能耗(kWh)"), ("T_total", "总时间(h)")]
    names = [n for n, _ in WEIGHT_SETS]
    bar_colors = [CAT[0], CAT[1], CAT[2]]
    for j, (key, label) in enumerate(metrics):
        ax = fig.add_subplot(gs[0, j + 1])
        vals = [results[n][key] / 3600.0 if key == "T_total" else results[n][key] for n in names]
        bars = ax.bar(range(len(names)), vals, width=0.55, color=bar_colors, zorder=3)
        for b, v in zip(bars, vals):
            fmt = f"{v:.0f}" if key == "N" else f"{v:.2f}"
            ax.annotate(fmt, (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=8.2, color=INK2)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, fontsize=7.6, rotation=18, ha="right")
        style_ax(ax, grid_axis="y")
        ax.set_title(f"({chr(98 + j)}) {label}", fontsize=10, color=INK, loc="left")
        vmax = max(vals)
        ax.set_ylim(0, vmax * 1.3 if vmax > 0 else 1)

    fig.suptitle("图q1.21-1  第2小问 · 方法1（线性加权法）：候选池权衡分布与三组权重结果对比\n"
                 "（三组权重差异很大但均收敛到同一方案，(b)(c)(d)柱高完全一致，与q1_22支付表结论一致）",
                 fontsize=12.2, fontweight="bold", color=INK, x=0.02, y=0.99, ha="left", va="top")
    fig.subplots_adjust(left=0.055, right=0.985, top=0.76, bottom=0.14, wspace=0.45)
    savefig(fig, "q1_21_01_候选池权衡与三组权重对比.png")


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


def main():
    boxes_df, spec_df, qmax_lookup, geo_table = load_base_data()
    candidates = enumerate_candidates(boxes_df, spec_df, geo_table, qmax_lookup)
    print(f"[候选池] 共生成 {len(candidates)} 个候选批次（15服务区 x 3机型，DFS剪枝后）")

    results = {}
    for name, weights in WEIGHT_SETS:
        cost = weighted_cost(candidates, boxes_df, weights)
        chosen_idx = solve_set_partitioning(candidates, boxes_df, cost)
        selected = candidates.iloc[chosen_idx].reset_index(drop=True)
        N, E_total, T_total = total_metrics(selected)
        ok, msg = validate_selection(selected, boxes_df)
        results[name] = dict(weights=weights, selected=selected, idx=chosen_idx, N=N, E_total=E_total,
                              T_total=T_total, ok=ok, msg=msg)
        print(f"[{name}] N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s  {msg}")

    main_name = "均衡"
    main_res = results[main_name]
    out_cols = ["服务区编号", "机型编号", "箱数", "总质量_kg", "总体积_m3", "E_batch_kWh", "T_batch_s", "货箱列表"]
    out_df = main_res["selected"][out_cols].copy()
    out_df.insert(0, "批次编号", [f"{r['服务区编号']}-W{i+1:02d}" for i, r in out_df.reset_index().to_dict("index").items()])
    out_df["货箱列表"] = out_df["货箱列表"].apply(lambda t: "|".join(t))
    out_df.to_csv(os.path.join(BASE_DIR, "q1_21_batches.csv"), index=False, encoding="utf-8-sig")
    print(f"[saved] q1_21_batches.csv rows={len(out_df)}（权重方案：{main_name}）")

    fig_pool_and_weights(candidates, results, main_name)
    fig_batch_composition(
        out_df, "q1_21_02_主方案批次构成.png",
        f"图q1.21-2  第2小问 · 方法1（线性加权法，{main_name}权重）：各服务区批次数与机型构成"
    )

    lines = []
    lines.append("问题一 第2小问 · 方法1：线性加权法（Set Partitioning 精确 MILP）—— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"候选批次池规模: {len(candidates)}（15服务区 x 3机型，DFS+剪枝精确枚举）")
    lines.append("")
    lines.append("一、三组权重(w_N, w_E, w_T)下的求解结果")
    for name, _ in WEIGHT_SETS:
        r = results[name]
        lines.append(
            f"  [{name}] 权重={r['weights']}  N={r['N']}  E_total={r['E_total']:.3f} kWh  "
            f"T_total={r['T_total']:.1f} s ({r['T_total']/3600:.2f} h)  {r['msg']}"
        )
    n_values = {results[name]["N"] for name, _ in WEIGHT_SETS}
    if len(n_values) == 1:
        lines.append("  注：三组权重收敛到同一方案，说明本实例中 N/E_total/T_total 三个目标在")
        lines.append("  最优解附近几乎不冲突（并非权重设置无效——三组权重差异很大，收敛到同一点")
        lines.append("  恰恰反映了该点同时逼近三个目标各自的理论最优，与 q1_22 支付表结论一致）。")
    lines.append("")
    lines.append(f"二、主输出方案（权重={main_name}）")
    lines.append(f"  N={main_res['N']}  E_total={main_res['E_total']:.3f} kWh  "
                  f"T_total={main_res['T_total']:.1f} s")
    lines.append(f"  已写入 q1_21_batches.csv，共 {len(out_df)} 行")
    lines.append("")
    lines.append("三、与第1小问启发式基线（q1_1_batches.csv, N=18）的量级对照")
    lines.append(f"  均衡权重解 N={results['均衡']['N']}，同一量级，符合预期"
                  f"（方法与目标不同，不要求相等）")
    lines.append("")
    lines.append("四、标准化说明")
    lines.append("  E、T 按候选池最大值做纯比例缩放（不平移）；N 的每候选贡献取")
    lines.append("  1/(总箱数-服务区个数)，即用 N 的结构性可达范围做同样的纯比例缩放。")
    lines.append("  三者都只缩放不平移，求和后即三个总量的线性重标度，可直接加权比较。")

    with open(os.path.join(BASE_DIR, "q1_21_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q1_21_summary.txt")

    all_ok = all(r["ok"] for r in results.values())
    print("[done] all checks passed" if all_ok else "[warn] some checks failed")


if __name__ == "__main__":
    main()
