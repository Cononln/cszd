# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一第2小问 · 方法2：理想点法/妥协规划（q1_22）

范围：与 q1_21.py 相同的候选批次池与集合划分（Set Partitioning）问题结构，
但求解方式不同——不做加权线性组合，而是先求出三个目标各自单独最优时能
达到的理想点，再求一个到理想点"距离最小"的妥协解。

步骤：
    1) 分别以 N、E_total、T_total 为单一目标各自求解一次 Set Partitioning
       MILP（q1_2_common.solve_set_partitioning），得到理想点
       (N*, E*, T*) = 三次单目标最优解各自的目标值；
    2) 用三次单目标解各自代入其余目标得到的"支付表"(payoff table)的行最大值
       近似 nadir 点 (N_nadir, E_nadir, T_nadir)（标准做法，精确 nadir 需要
       枚举所有有效解，代价过高，行业内普遍用支付表近似）；
    3) 构造标准化加权 Chebyshev（L-infinity）距离：
           z >= w_k * (f_k(x) - f_k*) / (nadir_k - f_k*)   for k in {N,E,T}
       在 MILP 中引入辅助变量 z，minimize z，三条约束线性化上式，
       用 scipy.optimize.milp 精确求解一次，得到本方法的妥协解。

运行方式：
    python q1_22.py
输出（当前目录 / figures/）：
    q1_22_batches.csv   妥协解的组批方案明细
    q1_22_summary.txt   理想点/nadir点/偏离度 + 校验
    figures/q1_22_01_支付表与归一化对比.png
    figures/q1_22_02_妥协解偏离度与目标空间位置.png
    figures/q1_22_03_妥协解批次构成.png
"""
import os

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import milp, LinearConstraint, Bounds

from q00 import style_ax, savefig, SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR
from q1_2_common import (
    load_base_data, enumerate_candidates, solve_set_partitioning,
    total_metrics, validate_selection, build_incidence,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OBJ_NAMES = ["N", "E_total", "T_total"]
WEIGHTS = (1 / 3, 1 / 3, 1 / 3)


def single_objective_costs(candidates):
    n = len(candidates)
    return {
        "N": np.ones(n),
        "E_total": candidates["E_batch_kWh"].values.astype(float),
        "T_total": candidates["T_batch_s"].values.astype(float),
    }


def solve_chebyshev(candidates, boxes_df, costs, ideal, nadir, weights):
    A, box_ids = build_incidence(boxes_df, candidates)
    m, n = A.shape

    # 决策变量 = [x_0..x_{n-1}, z]；覆盖约束的关联矩阵补一列0（不涉及z）
    zero_col = np.zeros((m, 1))
    A_cover = np.hstack([A.toarray(), zero_col])
    cover_constraint = LinearConstraint(A_cover, lb=np.ones(m), ub=np.ones(m))

    cheb_rows = []
    cheb_lb = []
    for k, w in zip(OBJ_NAMES, weights):
        rng = nadir[k] - ideal[k]
        if rng <= 1e-9:
            continue  # 该目标在三次单目标解中几乎不变化，不构成有效约束
        scaled_c = (w / rng) * costs[k]
        row = np.concatenate([-scaled_c, [1.0]])  # z - scaled_c.x >= -w/rng * f_k*
        cheb_rows.append(row)
        cheb_lb.append(-(w / rng) * ideal[k])
    cheb_constraint = LinearConstraint(np.vstack(cheb_rows), lb=np.array(cheb_lb), ub=np.inf)

    c = np.concatenate([np.zeros(n), [1.0]])
    integrality = np.concatenate([np.ones(n), [0]])
    bounds = Bounds(lb=np.concatenate([np.zeros(n), [0.0]]), ub=np.concatenate([np.ones(n), [np.inf]]))

    res = milp(c=c, constraints=[cover_constraint, cheb_constraint],
               integrality=integrality, bounds=bounds)
    if not res.success:
        raise RuntimeError(f"Chebyshev MILP求解失败: {res.message}")
    chosen_idx = np.where(res.x[:n] > 0.5)[0]
    return chosen_idx, res.x[n]


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------
ROW_NAMES = ["最小化 N 解", "最小化 E_total 解", "最小化 T_total 解", "妥协解"]
ROW_COLORS = [CAT[0], CAT[1], CAT[2], CAT[7]]


def _solution_table(payoff, compromise):
    return np.array([
        [payoff["N"]["N"], payoff["N"]["E_total"], payoff["N"]["T_total"] / 3600.0],
        [payoff["E_total"]["N"], payoff["E_total"]["E_total"], payoff["E_total"]["T_total"] / 3600.0],
        [payoff["T_total"]["N"], payoff["T_total"]["E_total"], payoff["T_total"]["T_total"] / 3600.0],
        [compromise["N"], compromise["E_total"], compromise["T_total"] / 3600.0],
    ])


def fig_payoff_table(payoff, compromise):
    col_labels = ["架次数 N", "总能耗\nE_total(kWh)", "总时间\nT_total(h)"]
    table = _solution_table(payoff, compromise)

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))

    ax = axes[0]
    vmin, vmax = table.min(axis=0), table.max(axis=0)
    vspan = np.where(vmax - vmin < 1e-9, 1.0, vmax - vmin)
    norm_tbl = (table - vmin) / vspan
    ax.imshow(norm_tbl, cmap="Blues", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=9.2)
    ax.set_yticks(range(len(ROW_NAMES)))
    ax.set_yticklabels(ROW_NAMES, fontsize=9.4)
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            txt_color = "white" if norm_tbl[i, j] > 0.6 else INK
            fmt = "{:.0f}" if j == 0 else "{:.3f}"
            ax.text(j, i, fmt.format(table[i, j]), ha="center", va="center", fontsize=9.6, color=txt_color)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, colors=INK2)
    ax.set_title("(a) 支付表（行=单独最小化该目标/妥协解，列=三目标取值；颜色=列内归一化）",
                 fontsize=9.8, color=INK, loc="left")

    ax = axes[1]
    x = np.arange(3)
    for name, row, color in zip(ROW_NAMES, norm_tbl, ROW_COLORS):
        is_comp = name == "妥协解"
        ax.plot(x, row, color=color, lw=2.6 if is_comp else 1.6, marker="o" if is_comp else "s",
                markersize=6.5, zorder=5 if is_comp else 3, label=name)
    ax.set_xticks(x)
    ax.set_xticklabels(col_labels, fontsize=9)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["理想点\n(0)", "nadir点\n(1)"], fontsize=8.4)
    for xi in x:
        ax.axvline(xi, color=GRID, lw=0.8, zorder=1)
    ax.set_ylim(-0.06, 1.06)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_facecolor(SURFACE)
    ax.set_title("(b) 归一化平行坐标：妥协解相对理想点/nadir点的位置", fontsize=9.8, color=INK, loc="left")
    ax.legend(loc="upper center", fontsize=8.2, frameon=False, bbox_to_anchor=(0.5, -0.18), ncol=4)

    fig.suptitle("图q1.22-1  第2小问 · 方法2（理想点法）：支付表与归一化目标位置对比",
                 fontsize=12.6, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.06, 1, 0.9))
    savefig(fig, "q1_22_01_支付表与归一化对比.png")


def fig_deviation_and_scatter(payoff, compromise, dev):
    pts = [payoff["N"], payoff["E_total"], payoff["T_total"], compromise]

    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.4))

    ax = axes[0]
    keys = ["N", "E_total", "T_total"]
    labels = ["架次数 N", "总能耗 E_total", "总时间 T_total"]
    vals = [dev[k] for k in keys]
    bars = ax.bar(range(3), vals, width=0.5, color=CAT[7], zorder=3)
    for b, v in zip(bars, vals):
        ax.annotate(f"+{v:.1f}%", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9.6, color=INK2)
    ax.set_xticks(range(3))
    ax.set_xticklabels(labels, fontsize=9.2)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("相对理想点的偏离（%）")
    ax.set_ylim(0, max(vals) * 1.3 if max(vals) > 0 else 1)
    ax.set_title("(a) 妥协解相对理想点的偏离幅度", fontsize=10.4, color=INK, loc="left")

    ax = axes[1]
    for name, p, color in zip(ROW_NAMES, pts, ROW_COLORS):
        is_comp = name == "妥协解"
        ax.scatter([p["E_total"]], [p["T_total"] / 3600.0], s=260 if is_comp else 110,
                   color=color, marker="*" if is_comp else "o", edgecolor=INK, linewidths=0.8,
                   zorder=5 if is_comp else 3, label=name)
        ax.annotate(f"N={p['N']}", (p["E_total"], p["T_total"] / 3600.0), xytext=(7, 6),
                    textcoords="offset points", fontsize=8.2, color=INK2)
    ax.margins(x=0.22, y=0.22)
    style_ax(ax, grid_axis="both")
    ax.set_xlabel("总能耗 E_total（kWh）")
    ax.set_ylabel("总时间 T_total（h）")
    ax.set_title("(b) 三个单目标最优解与妥协解在目标空间中的位置", fontsize=10.4, color=INK, loc="left")
    ax.legend(loc="best", fontsize=7.8, frameon=False)

    fig.suptitle("图q1.22-2  第2小问 · 方法2（理想点法）：妥协解偏离度与目标空间位置",
                 fontsize=12.6, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    savefig(fig, "q1_22_02_妥协解偏离度与目标空间位置.png")


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

    costs = single_objective_costs(candidates)

    payoff = {}   # payoff[目标k被单独最小化时的解][各目标取值]
    for k in OBJ_NAMES:
        chosen_idx = solve_set_partitioning(candidates, boxes_df, costs[k])
        selected = candidates.iloc[chosen_idx]
        N, E_total, T_total = total_metrics(selected)
        payoff[k] = {"N": N, "E_total": E_total, "T_total": T_total}
        print(f"[单目标最小化 {k}] -> N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s")

    ideal = {k: payoff[k][k] for k in OBJ_NAMES}
    nadir = {k: max(payoff[j][k] for j in OBJ_NAMES) for k in OBJ_NAMES}
    print(f"[理想点] {ideal}")
    print(f"[nadir点近似(支付表)] {nadir}")

    chosen_idx, z = solve_chebyshev(candidates, boxes_df, costs, ideal, nadir, WEIGHTS)
    selected = candidates.iloc[chosen_idx].reset_index(drop=True)
    N, E_total, T_total = total_metrics(selected)
    ok, msg = validate_selection(selected, boxes_df)
    print(f"[妥协解] N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s  z={z:.4f}  {msg}")

    out_cols = ["服务区编号", "机型编号", "箱数", "总质量_kg", "总体积_m3", "E_batch_kWh", "T_batch_s", "货箱列表"]
    out_df = selected[out_cols].copy()
    out_df.insert(0, "批次编号", [f"{r['服务区编号']}-I{i+1:02d}" for i, r in out_df.reset_index().to_dict("index").items()])
    out_df["货箱列表"] = out_df["货箱列表"].apply(lambda t: "|".join(t))
    out_df.to_csv(os.path.join(BASE_DIR, "q1_22_batches.csv"), index=False, encoding="utf-8-sig")
    print(f"[saved] q1_22_batches.csv rows={len(out_df)}")

    compromise = {"N": N, "E_total": E_total, "T_total": T_total}
    dev_n = 0.0 if ideal["N"] == 0 else (N - ideal["N"]) / max(ideal["N"], 1) * 100
    dev_e = (E_total - ideal["E_total"]) / ideal["E_total"] * 100
    dev_t = (T_total - ideal["T_total"]) / ideal["T_total"] * 100
    dev = {"N": dev_n, "E_total": dev_e, "T_total": dev_t}

    fig_payoff_table(payoff, compromise)
    fig_deviation_and_scatter(payoff, compromise, dev)
    fig_batch_composition(
        out_df, "q1_22_03_妥协解批次构成.png",
        "图q1.22-3  第2小问 · 方法2（理想点法）：妥协解各服务区批次数与机型构成"
    )

    lines = []
    lines.append("问题一 第2小问 · 方法2：理想点法/妥协规划（Chebyshev距离 + 精确 MILP）—— 结果汇总")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"候选批次池规模: {len(candidates)}（15服务区 x 3机型，DFS+剪枝精确枚举）")
    lines.append("")
    lines.append("一、支付表（每行=单独最小化该目标时，三个目标各自取值）")
    for k in OBJ_NAMES:
        r = payoff[k]
        lines.append(f"  单独最小化{k:9s}-> N={r['N']:>3}  E_total={r['E_total']:8.3f} kWh  T_total={r['T_total']:9.1f} s")
    lines.append("")
    lines.append("二、理想点 / nadir点（近似）")
    lines.append(f"  理想点: N*={ideal['N']}  E*={ideal['E_total']:.3f} kWh  T*={ideal['T_total']:.1f} s")
    lines.append(f"  nadir : N ={nadir['N']}  E ={nadir['E_total']:.3f} kWh  T ={nadir['T_total']:.1f} s")
    lines.append("")
    lines.append(f"三、妥协解（等权重 Chebyshev 距离最小化，w={WEIGHTS}）")
    lines.append(f"  N={N}  E_total={E_total:.3f} kWh  T_total={T_total:.1f} s  最小化后的 z={z:.4f}")
    lines.append(f"  相对理想点的偏离: N +{dev_n:.1f}%  E_total +{dev_e:.1f}%  T_total +{dev_t:.1f}%")
    lines.append(f"  {msg}")
    lines.append(f"  已写入 q1_22_batches.csv，共 {len(out_df)} 行")
    lines.append("")
    lines.append("四、与第1小问启发式基线（q1_1_batches.csv, N=18）的量级对照")
    lines.append(f"  妥协解 N={N}，同一量级，符合预期（方法与目标不同，不要求相等）")

    with open(os.path.join(BASE_DIR, "q1_22_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q1_22_summary.txt")
    print("[done] all checks passed" if ok else "[warn] some checks failed")


if __name__ == "__main__":
    main()
