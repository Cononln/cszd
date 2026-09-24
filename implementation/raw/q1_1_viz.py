# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一第1小问 求解结果可视化（q1_1_viz）

只对 q1_1.py 已算出的结果文件（q1_1_qmax.csv / q1_1_batches.csv）作图，
不重新求解、不引入任何新的建模假设或数值。配色与排版风格直接复用 q00.py
已建立的样式体系（style_ax / savefig / CAT / DRONE_COLOR 等），保持全篇
图表视觉语言一致。

统一的可视化约定（贯穿本脚本全部图表）：
    机型颜色 —— 复用 q00.py 的 DRONE_COLOR（A/B/C 三色，代表机型身份）。
    "能量受限"状态 —— 统一用 红色(STATUS_BIND) + 斜纹/描边 作为次级编码，
    不与机型颜色混用，避免颜色通道承载两种含义。

运行方式：
    python q1_1_viz.py
输出：
    ./figures/ 目录下新增 5 张 PNG（文件名以 q1_1_ 开头，与 q00.py 的
    01~13 号图并列存放）
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FuncFormatter

from q00 import (
    load_transport_drone,
    style_ax, savefig, FIG_DIR, BASE_DIR,
    SURFACE, INK, INK2, MUTED, BASELINE, CAT,
    DRONE_ORDER, DRONE_COLOR, DRONE_LABEL,
)

STATUS_OK = MUTED     # 灰色：质量受限（能量仍有富余）
STATUS_BIND = CAT[7]  # 红色：能量余量受限 —— 全篇统一使用这一种红色表达"受限"

F_QMAX = os.path.join(BASE_DIR, "q1_1_qmax.csv")
F_BATCH = os.path.join(BASE_DIR, "q1_1_batches.csv")


def load_results():
    qmax = pd.read_csv(F_QMAX, encoding="utf-8-sig")
    batches = pd.read_csv(F_BATCH, encoding="utf-8-sig")
    return qmax, batches


# ===========================================================================
# 图 q1_1-01：三种机型在各服务区的最大安全载荷 q_max(g,i)（分组柱状图）
# ===========================================================================
def fig_qmax_bars(qmax, spec):
    order = sorted(qmax["服务区编号"].unique())
    Qg = dict(zip(spec["机型编号"], spec["最大载货质量"]))

    fig, ax = plt.subplots(figsize=(13, 6.2))
    x = np.arange(len(order))
    n = len(DRONE_ORDER)
    width = 0.24
    for i, g in enumerate(DRONE_ORDER):
        sub = qmax[qmax["机型编号"] == g].set_index("服务区编号").reindex(order)
        offs = x + (i - (n - 1) / 2) * width
        is_bind = (sub["限制因素"] == "energy_margin").values
        vals = sub["q_max_kg"].values

        ax.bar(offs[~is_bind], vals[~is_bind], width=width * 0.92,
               color=DRONE_COLOR[g], zorder=3)
        if is_bind.any():
            ax.bar(offs[is_bind], vals[is_bind], width=width * 0.92,
                   color=DRONE_COLOR[g], hatch="////", edgecolor=STATUS_BIND,
                   linewidth=1.1, zorder=3)
            cap = Qg[g]
            ax.scatter(offs[is_bind], np.full(is_bind.sum(), cap), marker="_", s=170,
                       linewidths=1.6, color=STATUS_BIND, zorder=5)
            for xo, q in zip(offs[is_bind], vals[is_bind]):
                ax.plot([xo, xo], [q, cap], color=STATUS_BIND, lw=0.9, ls=":", zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels(order, fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("最大安全载荷 $q_{max}$（kg）")
    ax.set_title(
        "图q1.1-1  三种机型在各服务区单点往返任务下的最大安全载荷 $q_{max}(g,i)$\n"
        "（斜纹柱=被返航能量余量约束卡住；红色虚线标出该机型质量上限本应达到的高度）",
        loc="left", fontsize=12.5, fontweight="bold", color=INK)

    handles = [Patch(facecolor=DRONE_COLOR[g], label=DRONE_LABEL[g]) for g in DRONE_ORDER]
    handles.append(Patch(facecolor="white", edgecolor=STATUS_BIND, hatch="////",
                          label="能量余量受限（q_max < 机型质量上限）"))
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8.8, frameon=False,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    savefig(fig, "q1_1_01_机型最大安全载荷分组柱状图.png")


# ===========================================================================
# 图 q1_1-02：各机型×服务区的返航安全能量利用率热力图
# ===========================================================================
def fig_energy_heatmap(qmax):
    order = sorted(qmax["服务区编号"].unique())
    df = qmax.copy()
    df["能量利用率"] = df["往返总能耗_kWh_at_qmax"] / df["能量上限_kWh"]

    piv = df.pivot_table(index="服务区编号", columns="机型编号", values="能量利用率")
    piv = piv.reindex(index=order, columns=DRONE_ORDER)
    bind = df.pivot_table(index="服务区编号", columns="机型编号", values="限制因素", aggfunc="first")
    bind = bind.reindex(index=order, columns=DRONE_ORDER)

    vmin = float(np.nanmin(piv.values))
    vmax = 1.0

    fig, ax = plt.subplots(figsize=(6.0, 8.6))
    im = ax.imshow(piv.values, cmap="Blues", aspect="auto", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(DRONE_ORDER)))
    ax.set_xticklabels([DRONE_LABEL[g] for g in DRONE_ORDER], fontsize=8.4, rotation=12, ha="right")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=9.2)

    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            is_bind = bind.values[i, j] == "energy_margin"
            norm_v = (v - vmin) / (vmax - vmin + 1e-9)
            txt_color = "white" if norm_v > 0.6 else INK
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=8.4,
                     color=txt_color, fontweight="bold" if is_bind else "normal")
            if is_bind:
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                        edgecolor=STATUS_BIND, linewidth=2.0, zorder=5))

    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, colors=INK2)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.04)
    cb.set_label("往返总能耗 ÷ 返航安全能量上限", fontsize=9, color=INK)
    cb.outline.set_visible(False)
    ax.set_title(
        "图q1.1-2  各机型在各服务区的返航安全能量利用率（取 $q_{max}$ 时）\n"
        "（红框=该组合被能量余量卡住，其余为质量上限先卡住、能量仍有富余）",
        loc="left", fontsize=11.4, fontweight="bold", color=INK, pad=10)
    savefig(fig, "q1_1_02_能耗利用率热力图.png")


# ===========================================================================
# 图 q1_1-03：距离对最大安全载荷的影响（每机型一个子图）
# ===========================================================================
def fig_distance_scatter(qmax, spec):
    Qg = dict(zip(spec["机型编号"], spec["最大载货质量"]))
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.0))
    for ax, g in zip(axes, DRONE_ORDER):
        sub = qmax[qmax["机型编号"] == g].copy()
        sub["水平距离_km"] = sub["水平距离_m"] / 1000.0
        is_bind = sub["限制因素"] == "energy_margin"

        ax.axhline(Qg[g], color=BASELINE, lw=1.1, ls="--", zorder=1)
        ax.scatter(sub.loc[~is_bind, "水平距离_km"], sub.loc[~is_bind, "q_max_kg"],
                   s=70, color=STATUS_OK, edgecolor=INK2, linewidths=0.6, zorder=3)
        ax.scatter(sub.loc[is_bind, "水平距离_km"], sub.loc[is_bind, "q_max_kg"],
                   s=85, color=STATUS_BIND, edgecolor=INK, linewidths=0.7, zorder=4)

        ylim = Qg[g] * 1.12
        xmin, xmax = sub["水平距离_km"].min(), sub["水平距离_km"].max()
        xpad = (xmax - xmin) * 0.08
        bind_pts = sub[is_bind].sort_values("q_max_kg", ascending=False)
        n_bind = len(bind_pts)
        if n_bind == 1:
            r = bind_pts.iloc[0]
            ax.annotate(r["服务区编号"], (r["水平距离_km"], r["q_max_kg"]), xytext=(6, -8),
                        textcoords="offset points", fontsize=8, color=INK)
            ax.set_xlim(xmin - xpad, xmax + xpad)
        elif n_bind > 1:
            # 多个能量受限点在图上彼此过近（数值本身接近），改用堆叠引线标注避免文字重叠
            step = ylim * 0.075
            y0 = min(ylim * 0.97, bind_pts["q_max_kg"].max() + ylim * 0.12)
            x_text = xmax + xpad * 2.2
            for i, (_, r) in enumerate(bind_pts.iterrows()):
                ax.annotate(r["服务区编号"], xy=(r["水平距离_km"], r["q_max_kg"]),
                            xytext=(x_text, y0 - i * step), textcoords="data",
                            fontsize=8, color=INK, va="center", ha="left",
                            arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6,
                                             shrinkA=2, shrinkB=4))
            ax.set_xlim(xmin - xpad, x_text + xpad * 6)
        else:
            ax.set_xlim(xmin - xpad, xmax + xpad)

        style_ax(ax, grid_axis="both")
        ax.set_xlabel("到 O01 的水平距离（km）")
        if g == DRONE_ORDER[0]:
            ax.set_ylabel("最大安全载荷 $q_{max}$（kg）")
        ax.set_title(DRONE_LABEL[g], fontsize=10.6, color=INK, loc="left")
        ax.set_ylim(0, ylim)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=STATUS_OK,
               markeredgecolor=INK2, markersize=9, label="质量受限（能量仍有富余）"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=STATUS_BIND,
               markeredgecolor=INK, markersize=9, label="能量余量受限（已标注服务区编号）"),
        Line2D([0], [0], color=BASELINE, lw=1.1, ls="--", label="机型最大载货质量 $Q_g$"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=9, frameon=False,
               bbox_to_anchor=(0.5, -0.03))
    fig.suptitle("图q1.1-3  距离越远/爬升越高，越容易被返航能量余量卡住（A型始终未被卡住）",
                 fontsize=13, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.09, 1, 0.90))
    savefig(fig, "q1_1_03_距离对最大安全载荷的影响.png")


# ===========================================================================
# 图 q1_1-04：组批方案总览（机型使用次数 + 逐批次装载利用率）
# ===========================================================================
def fig_batch_overview(batches):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.0), gridspec_kw={"width_ratios": [1, 2.1]})

    ax = axes[0]
    cnt = batches["机型编号"].value_counts().reindex(DRONE_ORDER, fill_value=0)
    bars = ax.bar(DRONE_ORDER, cnt.values, width=0.55,
                   color=[DRONE_COLOR[g] for g in DRONE_ORDER], zorder=3)
    for b, v in zip(bars, cnt.values):
        ax.annotate(f"{int(v)}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=10.5, color=INK2)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("使用批次数（架次）")
    ax.set_title(f"(a) 各机型使用批次数（共{len(batches)}架次）", fontsize=11, color=INK, loc="left")

    ax = axes[1]
    df = batches.sort_values(["服务区编号", "批次编号"]).set_index("批次编号")
    x = np.arange(len(df))
    for xi, mu, vu in zip(x, df["质量利用率"], df["体积利用率"]):
        ax.plot([xi, xi], [mu, vu], color=BASELINE, lw=1.4, zorder=2)
    ax.scatter(x, df["质量利用率"], s=48, color=CAT[0], zorder=3, label="质量利用率")
    ax.scatter(x, df["体积利用率"], s=48, color=CAT[4], zorder=3, label="体积利用率")
    ax.axhline(1.0, color=STATUS_BIND, lw=1.0, ls=":", zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(df.index, fontsize=7.3, rotation=60, ha="right")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, pos: f"{v:.0%}"))
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("装载利用率")
    ax.set_title(f"(b) 逐批次质量/体积利用率对比（按服务区排序，共{len(df)}批）",
                 fontsize=11, color=INK, loc="left")
    ax.legend(loc="lower right", fontsize=8.8, frameon=False)

    fig.suptitle("图q1.1-4  第1小问组批方案总览：机型使用分布与逐批次装载利用率",
                  fontsize=13.5, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    savefig(fig, "q1_1_04_组批方案总览.png")


# ===========================================================================
# 图 q1_1-05：各服务区货箱组批构成（分段横向堆叠条）
# ===========================================================================
def fig_batch_composition(batches):
    order = sorted(batches["服务区编号"].unique())
    fig, ax = plt.subplots(figsize=(11, 8.0))
    y = np.arange(len(order))
    gap = 1.2  # kg，仅作段间可视留白，不代表任何实际物理间隔

    for yi, sa in zip(y, order):
        sub = batches[batches["服务区编号"] == sa].sort_values("批次编号")
        left = 0.0
        for _, r in sub.iterrows():
            g = r["机型编号"]
            w = r["总质量_kg"]
            ax.barh(yi, w, left=left, height=0.6, color=DRONE_COLOR[g],
                    edgecolor=SURFACE, linewidth=1.6, zorder=3)
            label = f"{g}｜{r['质量利用率']:.0%}"
            if w >= 20:
                ax.text(left + w / 2, yi, label, ha="center", va="center",
                         fontsize=7.6, color="white", fontweight="bold", zorder=4)
            else:
                ax.annotate(label, (left + w, yi), xytext=(4, 0), textcoords="offset points",
                            ha="left", va="center", fontsize=7.3, color=INK, zorder=4)
            left += w + gap

    ax.set_yticks(y)
    ax.set_yticklabels(order, fontsize=9.5)
    ax.invert_yaxis()
    style_ax(ax, grid_axis="x")
    ax.set_xlabel("批次总质量（kg；段间留白仅为可视分隔，不代表实际间隔）")
    ax.set_title(
        "图q1.1-5  第1小问：各服务区货箱组批构成（每段=一个批次/架次，颜色=机型，标注质量利用率）",
        loc="left", fontsize=12.3, fontweight="bold", color=INK, pad=10)
    handles = [Patch(facecolor=DRONE_COLOR[g], label=DRONE_LABEL[g]) for g in DRONE_ORDER]
    ax.legend(handles=handles, loc="lower right", fontsize=9, frameon=False)
    fig.tight_layout()
    savefig(fig, "q1_1_05_各服务区组批构成.png")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    qmax, batches = load_results()
    spec, _fleet, _battery = load_transport_drone()

    fig_qmax_bars(qmax, spec)
    fig_energy_heatmap(qmax)
    fig_distance_scatter(qmax, spec)
    fig_batch_overview(batches)
    fig_batch_composition(batches)

    print(f"\n全部图表已输出至：{FIG_DIR}")


if __name__ == "__main__":
    main()
