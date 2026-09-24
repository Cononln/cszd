# -*- coding: utf-8 -*-
"""问题四配图：分区方案权衡、TOPSIS 评价、资源缺口、工作量均衡与耦合结构。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.style import (GCOLOR, GNAME, PALETTE, save, despine, tag, apply_theme)
from common.route import SIDS
from common.viz import sankey, radar

apply_theme()
RES = Path(__file__).resolve().parents[2] / "results"

PA = pd.read_csv(RES / "q4_partition_all.csv")
GAP = pd.read_csv(RES / "q4_gap.csv")
GD = pd.read_csv(RES / "q4_group_detail.csv")
TRIPS = pd.read_csv(RES / "q2_transport_trips.csv")
J = json.loads((RES / "q4_results.json").read_text(encoding="utf-8"))
ATOMS = J["atoms"]
INV = J["inventory"]
BASE = J["baseline_k1"]
BEST = {int(s["k"]): s for s in J["summary"]}
KCOL = {2: "#4C72B0", 3: "#DD8452"}

# K=1 基线的规模指数，与 q4_partition.py 的算法完全一致（逐类除以库存再求和）
BASE_IDX = (sum(BASE["drones"][g] / INV["drones"][g] for g in "ABC")
            + sum(BASE["batteries"][g] / INV["batteries"][g] for g in "ABC")
            + BASE["relay_drones"] / INV["relay_drones"]
            + BASE["relay_modules"] / INV["relay_modules"])


def fig_q4_partition_scatter():
    """图：13 个合法分区方案的规模—缺口权衡与 TOPSIS 排序。"""
    fig, ax = plt.subplots(figsize=(9.4, 4.8))
    for k in (2, 3):
        d = PA[PA.k == k]
        sc = ax.scatter(d["配置规模"], d["资源缺口"], s=210,
                        c=d["组间不均衡"], cmap="viridis_r", vmin=0.4, vmax=1.3,
                        edgecolor=KCOL[k], linewidth=1.6, zorder=4,
                        label=f"K={k}（{len(d)} 个合法方案）")
    ax.scatter([BASE["scale"]], [BASE["gap"]], marker="*", s=430,
               color="#C44E52", edgecolor="white", linewidth=1.2, zorder=6,
               label="K=1 整体执行基线")
    for k in (2, 3):
        b = BEST[k]
        ax.annotate(f'K={k} 最优\n得分 {b["score"]:.3f}',
                    (b["scale"], b["gap"]), textcoords="offset points",
                    xytext=(12, -22), fontsize=8.2, color=KCOL[k],
                    arrowprops=dict(arrowstyle="->", color=KCOL[k], lw=1.2))
    ax.set_xlabel("配置规模 / 件")
    ax.set_ylabel("资源缺口 / 件")
    cb = fig.colorbar(sc, ax=ax, pad=0.02, fraction=0.045)
    cb.set_label("组间工作量不均衡度", fontsize=8.8)
    ax.legend(fontsize=8.4, loc="upper left")
    despine(ax)
    save(fig, "q4_partition_scatter")


def fig_q4_topsis_radar():
    """图：K=1/2/3 代表方案在三项评价准则上的对比。"""
    crit = ["规模指数", "资源缺口", "组间不均衡"]
    sub = PA[crit].to_numpy(float)
    lo, hi = sub.min(axis=0), sub.max(axis=0)
    span = np.where(hi - lo < 1e-12, 1.0, hi - lo)

    def nz(row):
        return 1.0 - (np.asarray(row, float) - lo) / span   # 成本型，越小得分越高

    b2 = PA[(PA.k == 2) & (PA["配置规模"] == BEST[2]["scale"]) &
            (np.isclose(PA["组间不均衡"], BEST[2]["imbalance"]))].iloc[0]
    b3 = PA[(PA.k == 3) & (PA["配置规模"] == BEST[3]["scale"]) &
            (np.isclose(PA["组间不均衡"], BEST[3]["imbalance"]))].iloc[0]
    base_row = [BASE_IDX, BASE["gap"], float(PA["组间不均衡"].max())]
    series = [("K=1 基线", nz(base_row)),
              ("K=2 最优", nz(b2[crit])),
              ("K=3 最优", nz(b3[crit]))]
    colors = ["#C44E52", "#4C72B0", "#DD8452"]
    fig, ax = plt.subplots(figsize=(5.6, 5.2), subplot_kw=dict(polar=True))
    radar(ax, ["规模指数\n(小为优)", "资源缺口\n(小为优)", "组间不均衡\n(小为优)"],
          series, colors)
    ax.legend(fontsize=8.6, loc="upper right", bbox_to_anchor=(1.26, 1.12))
    save(fig, "q4_topsis_radar")


def fig_q4_gap_waterfall():
    """图：最优 K=2 方案的逐类资源供需与缺口。"""
    d = GAP[GAP.K == 2].copy().reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10.2, 4.4))
    x = np.arange(len(d))
    ax.bar(x - 0.20, d["库存量"], width=0.38, color="#B8C4D9", zorder=3,
           label="库存量")
    ax.bar(x + 0.20, d["需求量"], width=0.38,
           color=["#C44E52" if g > 0 else "#55A868" for g in d["缺口"]],
           zorder=3, label="需求量（红=超库存）")
    for i, r in d.iterrows():
        if r["缺口"] > 0:
            ax.annotate(f'缺口 {int(r["缺口"])}', (i + 0.20, r["需求量"]),
                        textcoords="offset points", xytext=(0, 5), ha="center",
                        fontsize=8.0, color="#C44E52")
    ax.set_xticks(x)
    ax.set_xticklabels(d["资源类别"], rotation=22, ha="right", fontsize=8.2)
    ax.set_ylabel("数量 / 件")
    ax.legend(fontsize=8.4)
    despine(ax)
    save(fig, "q4_gap_waterfall")


def fig_q4_workload_balance():
    """图：最优方案的组间工作量与资源占用均衡性。"""
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2))
    for ax, k in zip(axes, (2, 3)):
        d = GD[GD.K == k].reset_index(drop=True)
        wl = pd.to_numeric(d["工作量kWh"], errors="coerce").to_numpy(float)
        trips = pd.to_numeric(
            d["运输架次数"].astype(str).str.split(";").str[0],
            errors="coerce").to_numpy(float)
        x = np.arange(len(wl))
        ax.bar(x, wl, width=0.55, color=[PALETTE[i] for i in range(len(wl))],
               zorder=3)
        for i, (w, t) in enumerate(zip(wl, trips)):
            ax.text(i, w + max(wl) * 0.02, f"{t:.0f} 架次", ha="center",
                    fontsize=8.2, color="#444444")
        ax.axhline(wl.mean(), color="#C44E52", ls="--", lw=1.4, zorder=4,
                   label=f"均值 {wl.mean():.2f} kWh")
        cv = wl.std() / max(wl.mean(), 1e-9)
        ax.set_xticks(x)
        ax.set_xticklabels([f"组{i+1}" for i in range(len(wl))], fontsize=9)
        ax.set_ylabel("组内运输工作量 / kWh")
        ax.set_title(f'K={k}（变异系数 {cv:.3f}）', pad=8)
        ax.legend(fontsize=8.2)
        ax.set_ylim(0, wl.max() * 1.26)
        despine(ax)
        tag(ax, "(a)" if k == 2 else "(b)")
    save(fig, "q4_workload_balance")


def fig_q4_partition_sankey():
    """图：最优 K=2 方案中服务区到任务组的归属流向。"""
    b = BEST[2]
    left, right, flows = [], [], []
    # 从 q4_config.csv 读回最终配置（与提交表一致）
    cfg = pd.read_csv(RES / "q4_config.csv")
    cfg = cfg[cfg.iloc[:, 0] == 2]
    gi = {}
    for i, (_, r) in enumerate(cfg.iterrows()):
        areas = [a.strip() for a in str(r["服务区列表"]).split("、") if a.strip()]
        gi[f"组{i+1}"] = i
        right.append((f'组{i+1}（{len(areas)} 区）', float(len(areas)),
                      [GCOLOR["A"], GCOLOR["B"], GCOLOR["C"]][i % 3]))
        for a in areas:
            left.append((a, 1.0, "#B8C4D9"))
    li = {lab: i for i, (lab, _, _) in enumerate(left)}
    for i, (_, r) in enumerate(cfg.iterrows()):
        for a in [x.strip() for x in str(r["服务区列表"]).split("、") if x.strip()]:
            if a in li:
                flows.append((li[a], gi[f"组{i+1}"], 1.0,
                              [GCOLOR["A"], GCOLOR["B"], GCOLOR["C"]][i % 3]))
    fig, ax = plt.subplots(figsize=(9.0, 5.4))
    sankey(ax, left, right, flows, flow_label=False, alpha=0.34, label_fs=8.4,
           value_fmt="{:.0f}")
    ax.set_title("服务区归属流向", pad=6)
    save(fig, "q4_partition_sankey")


def fig_q4_atom_graph():
    """图：同架次共载关系诱导的服务区耦合结构。"""
    import networkx as nx
    G = nx.Graph()
    G.add_nodes_from(SIDS)
    for _, r in TRIPS.iterrows():
        a = [x.strip() for x in str(r["stops"]).split("->") if x.strip()]
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                G.add_edge(a[i], a[j])
    comp = {}
    for ci, c in enumerate(nx.connected_components(G)):
        for n in c:
            comp[n] = ci
    sizes = sorted((len(c) for c in nx.connected_components(G)), reverse=True)
    pos = nx.spring_layout(G, seed=7, k=0.95, iterations=260)
    fig, ax = plt.subplots(figsize=(8.2, 6.4))
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#BBBBBB", width=1.1,
                           alpha=0.8)
    for ci, c in enumerate(nx.connected_components(G)):
        nx.draw_networkx_nodes(G, pos, nodelist=list(c), ax=ax,
                               node_size=560 if len(c) > 1 else 300,
                               node_color=PALETTE[ci % len(PALETTE)],
                               edgecolors="white", linewidths=1.3)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=7.2, font_color="#222222")
    ax.axis("off")
    ax.set_title(f"共载耦合结构（{len(sizes)} 个耦合原子，最大 {sizes[0]} 区）",
                 pad=6)
    save(fig, "q4_atom_graph")


def fig_q4_stirling():
    """图：合法划分数的理论枚举规模（去标签化前后）。"""
    from math import comb, factorial
    n = len(ATOMS)

    def stirling2(nn, kk):
        """第二类斯特林数：把 nn 个可区分元素划成 kk 个非空无标号组。"""
        return sum((-1) ** i * comb(kk, i) * (kk - i) ** nn
                   for i in range(kk + 1)) // factorial(kk)

    ks = np.arange(1, n + 1)
    legal = np.array([stirling2(n, int(k)) for k in ks], float)
    naive = np.array([float(k) ** n for k in ks])
    fig, ax = plt.subplots(figsize=(7.8, 4.3))
    x = np.arange(len(ks))
    ax.bar(x - 0.19, naive, width=0.36, color="#DD8452", zorder=3,
           label=f"朴素枚举 $k^{{{n}}}$")
    ax.bar(x + 0.19, legal, width=0.36, color="#4C72B0", zorder=3,
           label="去标签化合法划分 $S(4,k)$")
    for i in range(len(ks)):
        ax.text(i - 0.19, naive[i] * 1.10, f"{naive[i]:.0f}", ha="center",
                fontsize=8.2, color="#DD8452")
        ax.text(i + 0.19, legal[i] * 1.10, f"{legal[i]:.0f}", ha="center",
                fontsize=8.2, color="#4C72B0")
    ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels([f"K={k}" for k in ks])
    ax.set_ylabel("划分方案数 / 个（对数轴）")
    ax.legend(fontsize=8.6)
    despine(ax)
    save(fig, "q4_stirling")


if __name__ == "__main__":
    fig_q4_partition_scatter()
    fig_q4_topsis_radar()
    fig_q4_gap_waterfall()
    fig_q4_workload_balance()
    fig_q4_partition_sankey()
    fig_q4_atom_graph()
    fig_q4_stirling()
    print("Q4 配图完成")
