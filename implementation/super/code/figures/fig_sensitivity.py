# -*- coding: utf-8 -*-
"""灵敏度分析配图：问题二的充电周转灵敏度与问题三的通信参数灵敏度。

两幅图的数据分别来自
    results/q2_sensitivity.csv   —— 电池等效充电时间整体缩放 k 倍后重跑完整求解
    results/q3_sensitivity.csv   —— 在固定运输方案下重算中断区间
均为实测结果，不含任何手工填入的数值。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.style import PALETTE, apply_theme, despine, save, tag

apply_theme()
RES = Path(__file__).resolve().parents[2] / "results"

C_BAR = "#4C72B0"
C_LINE = "#C44E52"
C_ALT = "#55A868"
C_PUR = "#8172B3"


# ------------------------------------------------------------------ 问题二
def fig_sens_q2_charge():
    """图：电池等效充电时间对调度结果的影响。"""
    d = pd.read_csv(RES / "q2_sensitivity.csv").sort_values("scale")
    x = np.arange(len(d))
    lbl = ["充电快 20%", "基准", "充电慢 20%"]
    base_i = int(np.argmin(np.abs(d["scale"].values - 1.0)))

    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.3))

    # (a) 架次数与完工期
    ax = axes[0]
    b = ax.bar(x, d["n_trips"], width=0.52, color=C_BAR, alpha=0.9, zorder=3,
               label="运输架次数")
    for xi, v in zip(x, d["n_trips"]):
        ax.text(xi, v + 0.5, "%d" % v, ha="center", fontsize=9, color=C_BAR)
    ax.set_ylabel("运输架次数", color=C_BAR)
    ax.tick_params(axis="y", colors=C_BAR)
    ax.set_ylim(0, d["n_trips"].max() * 1.45)
    ax2 = ax.twinx()
    yh = d["makespan"] / 3600.0
    lo_, hi_ = yh.min(), yh.max()
    ax2.set_ylim(lo_ - (hi_ - lo_) * 0.35, hi_ + (hi_ - lo_) * 0.22)
    ax2.plot(x, yh, "o-", color=C_LINE, lw=2.0, ms=8, zorder=5, label="完工期")
    for xi, v in zip(x, yh):
        dy = -15 if xi == base_i else 10
        ax2.annotate("%.2f h" % v, (xi, v), textcoords="offset points",
                     xytext=(0, dy), ha="center", fontsize=8.4, color=C_LINE,
                     zorder=7,
                     bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
    ax2.set_ylabel("完工期 / h", color=C_LINE)
    ax2.tick_params(axis="y", colors=C_LINE)
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8.6, loc="lower center",
              framealpha=0.92)
    ax.set_title("架次数与完工期", fontsize=11)
    despine(ax)
    tag(ax, "(a)")

    # (b) 总能耗与单位质量能耗
    ax = axes[1]
    ax.bar(x, d["energy"], width=0.52, color=C_ALT, alpha=0.9, zorder=3,
           label="总运输能耗")
    for xi, v in zip(x, d["energy"]):
        dy = -12 if xi == base_i else 6
        ax.annotate("%.2f" % v, (xi, v), textcoords="offset points",
                    xytext=(0, dy), ha="center", fontsize=9, color=C_ALT,
                    zorder=7,
                    bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
    ax.set_ylabel("总运输能耗 / kWh", color=C_ALT)
    ax.tick_params(axis="y", colors=C_ALT)
    ax.set_ylim(0, d["energy"].max() * 1.30)
    ax2 = ax.twinx()
    per = d["energy"] / d["n_trips"]
    ax2.set_ylim(per.min() - (per.max() - per.min()) * 0.30,
                 per.max() + (per.max() - per.min()) * 0.28)
    xo = x + 0.17                      # 右移，避开柱顶的能耗标注
    ax2.plot(xo, per, "D--", color=C_PUR, lw=1.8, ms=7, zorder=5,
             label="单架次平均能耗")
    for xi, v in zip(xo, per):
        ax2.annotate("%.2f" % v, (xi, v), textcoords="offset points",
                     xytext=(0, 10), ha="center", fontsize=8.2, color=C_PUR,
                     zorder=7,
                     bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
    ax2.set_ylabel("单架次平均能耗 / kWh", color=C_PUR)
    ax2.tick_params(axis="y", colors=C_PUR)
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8.6, loc="lower center")
    ax.set_title("能耗总量与单架次强度", fontsize=11)
    despine(ax)
    tag(ax, "(b)")

    # (c) 准时率与超期货箱数（单一坐标轴，逐柱标注两项指标）
    ax = axes[2]
    rate = d["on_time_rate"] * 100.0
    cols = [C_ALT if v >= 99.99 else "#C44E52" for v in rate]
    ax.bar(x, rate, width=0.52, color=cols, alpha=0.9, zorder=3)
    for xi, v, nb in zip(x, rate, d["late_boxes"]):
        ax.annotate("%.0f%%" % v, (xi, v), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=9.4, color="#333333",
                    zorder=7)
        ax.annotate("超期 %d 箱" % nb, (xi, v), textcoords="offset points",
                    xytext=(0, -16), ha="center", fontsize=8.6,
                    color="white" if v > 20 else "#333333",
                    fontweight="bold", zorder=7)
    ax.axhline(100, color="#8C8C8C", ls=":", lw=1.2, zorder=1)
    ax.text(-0.42, 101.2, "100%", fontsize=8.4, color="#8C8C8C",
            ha="left")
    ax.set_ylabel("准时送达率 / %")
    ax.set_ylim(0, 118)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_title("时限满足水平", fontsize=11)
    despine(ax)
    tag(ax, "(c)")

    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(lbl, fontsize=9.2)
        ax.set_xlabel("电池等效完全充电时间 $T_{full}$")
    save(fig, "sens_q2_charge")


# ------------------------------------------------------------------ 问题三
def fig_sens_q3_comm():
    """图：衰落裕量与地形遮挡附加损耗对通信中断的影响。"""
    d = pd.read_csv(RES / "q3_sensitivity.csv")
    m = d[d["param"] == "M"].sort_values("value")
    lo = d[d["param"] == "L_obs"].sort_values("value")

    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.4))
    for ax, dd, xl, base, ttl in (
            (axes[0], m, "衰落裕量 $M$ / dB", 8.0, "衰落裕量 $M$"),
            (axes[1], lo, "遮挡附加损耗 $L_{obs}$ / dB", 10.0,
             "遮挡附加损耗 $L_{obs}$")):
        x = np.arange(len(dd))
        base_i = int(np.argmin(np.abs(dd["value"].values - base)))
        colors = [C_LINE if i == base_i else C_BAR for i in range(len(dd))]
        ax.bar(x, dd["n_seg"], width=0.56, color=colors, alpha=0.9, zorder=3,
               label="中断段数（基准参数为红色）")
        for xi, v in zip(x, dd["n_seg"]):
            ax.text(xi, v + 0.7, "%d" % v, ha="center", fontsize=9, color=C_BAR)
        ax.set_ylabel("中断段数 / 段", color=C_BAR)
        ax.tick_params(axis="y", colors=C_BAR)
        ax.set_ylim(0, dd["n_seg"].max() * 1.30)
        ax2 = ax.twinx()
        ax2.plot(x, dd["total_s"] / 3600.0, "o-", color=C_PUR, lw=2.0, ms=8,
                 zorder=5, label="累计中断时长")
        for xi, v in zip(x, dd["total_s"] / 3600.0):
            ax2.annotate("%.1f h" % v, (xi, v), textcoords="offset points",
                         xytext=(0, 10), ha="center", fontsize=8.2, color=C_PUR,
                         zorder=7,
                         bbox=dict(fc="white", ec="none", alpha=0.85, pad=0.8))
        ax2.set_ylabel("累计中断时长 / h", color=C_PUR)
        ax2.tick_params(axis="y", colors=C_PUR)
        ax2.set_ylim(0, dd["total_s"].max() / 3600.0 * 1.28)
        ax2.grid(False)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, fontsize=8.4, loc="upper left")
        ax.set_xticks(x)
        ax.set_xticklabels(["%.0f" % v for v in dd["value"]], fontsize=9.4)
        ax.set_xlabel(xl)
        ax.set_title(ttl, fontsize=11)
        despine(ax)
    tag(axes[0], "(a)")
    tag(axes[1], "(b)")
    save(fig, "sens_q3_comm")


# ------------------------------------------------------------------ 问题四
def fig_sens_q4_weight():
    """图：评价准则权重对分区方案排序的影响。"""
    d = pd.read_csv(RES / "q4_weight_sensitivity.csv")
    order = ["熵权法（正文）", "等权", "两准则", "单准则"]
    crit = ["规模指数", "资源缺口", "组间不均衡"]
    cw = [C_BAR, C_ALT, C_PUR]

    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.4))

    # (a) 四种赋权方式下的权重构成
    ax = axes[0]
    x = np.arange(len(order))
    bottom = np.zeros(len(order))
    for c, col in zip(crit, cw):
        w = []
        for name in order:
            r = d[d["赋权方式"] == name].iloc[0]
            w.append(float(r["权重"].split("/")[crit.index(c)]))
        w = np.array(w)
        ax.bar(x, w, 0.56, bottom=bottom, color=col, alpha=0.92, zorder=3,
               label=c)
        for xi, wi, bi in zip(x, w, bottom):
            if wi > 0.06:
                ax.text(xi, bi + wi / 2, "%.2f" % wi, ha="center",
                        va="center", fontsize=8.4, color="white",
                        fontweight="bold", zorder=6)
        bottom += w
    ax.set_ylim(0, 1.34)
    ax.set_yticks([0, 0.25, 0.50, 0.75, 1.00])
    ax.set_ylabel("准则权重")
    ax.set_xticks(x)
    ax.set_xticklabels(["熵权法\n（正文）", "等权", "两准则", "单准则"],
                       fontsize=9.0)
    ax.legend(fontsize=8.4, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, 1.005), framealpha=0.92)
    ax.set_title("赋权方式与权重构成", fontsize=11)
    despine(ax)
    tag(ax, "(a)")

    # (b) 各赋权方式下 K=2 与 K=3 最优方案的准则值热力图
    ax = axes[1]
    base2 = {c: float(d[(d["赋权方式"] == "熵权法（正文）") & (d["K"] == 2)]
                      .iloc[0][c]) for c in crit}
    M = np.zeros((len(order), 2 * len(crit)))
    for i, name in enumerate(order):
        for k_, off in ((2, 0), (3, len(crit))):
            r = d[(d["赋权方式"] == name) & (d["K"] == k_)].iloc[0]
            for j, c in enumerate(crit):
                M[i, off + j] = float(r[c]) / base2[c]
    im = ax.imshow(M, cmap="RdYlGn_r", aspect="auto", vmin=0.85,
                   vmax=M.max() * 1.02)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            ax.text(j, i, "%.2f" % M[i, j], ha="center", va="center",
                    fontsize=8.4, color="#222222", zorder=5)
    ax.axvline(len(crit) - 0.5, color="white", lw=3.0, zorder=4)
    ax.set_xticks(np.arange(2 * len(crit)))
    ax.set_xticklabels(crit * 2, fontsize=8.2)
    ax.set_yticks(np.arange(len(order)))
    ax.set_yticklabels([n.replace("（正文）", "") for n in order], fontsize=9.0)
    ax.text(len(crit) / 2 - 0.5, -0.92, "$K=2$ 最优方案", ha="center",
            fontsize=9.2, color=C_BAR, fontweight="bold")
    ax.text(len(crit) * 1.5 - 0.5, -0.92, "$K=3$ 最优方案", ha="center",
            fontsize=9.2, color=C_LINE, fontweight="bold")
    ax.set_xticks(np.arange(-0.5, 2 * len(crit), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(order), 1), minor=True)
    ax.grid(which="minor", color="white", lw=1.6)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(axis="both", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.036, pad=0.03)
    cb.set_label("相对熵权法 $K=2$ 基准的倍数（成本型，越小越好）",
                 fontsize=8.4)
    cb.ax.tick_params(labelsize=8.0)
    ax.set_title("各赋权下最优方案的准则值", fontsize=11)
    tag(ax, "(b)")

    fig.subplots_adjust(wspace=0.30)
    save(fig, "sens_q4_weight")


if __name__ == "__main__":
    fig_sens_q2_charge()
    fig_sens_q3_comm()
    fig_sens_q4_weight()
