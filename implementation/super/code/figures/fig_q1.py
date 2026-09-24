# -*- coding: utf-8 -*-
"""问题一配图：等效航程、最大安全载荷、组批 Pareto 前沿与 ρ 灵敏度。"""
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
from common.route import GTS, SIDS
from common.data import load_boxes

apply_theme()
RES = Path(__file__).resolve().parents[2] / "results"
FIG = Path(__file__).resolve().parents[2] / "figures"


def fig_range_curve():
    """图：三机型等效航程随载荷衰减 + 各服务区往返里程标尺。"""
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.1),
                             gridspec_kw=dict(width_ratios=[1, 1]))
    ax = axes[0]
    q = np.linspace(0, 1, 200)
    for g in "ABC":
        gt = GTS[g]
        L = gt["L0"] - (gt["L0"] - gt["LF"]) * q ** 1.5
        ax.plot(q * gt["Q"], L / 1000, color=GCOLOR[g], lw=2.0,
                label=f'{GNAME[g]}（$L^0$={gt["L0"]/1000:.0f} km，'
                      f'$L^F$={gt["LF"]/1000:.0f} km，$Q$={gt["Q"]:.0f} kg）')
        ax.scatter([gt["Q"]], [gt["LF"] / 1000], color=GCOLOR[g], zorder=5,
                   edgecolor="white", linewidth=1.2, s=55)
    ax.set_xlabel("有效载荷 $q$ / kg")
    ax.set_ylabel("等效航程 $L_g(q)$ / km")
    ax.set_title("等效航程随载荷的衰减", pad=8)
    ax.legend(loc="lower left", fontsize=8.4)
    despine(ax)
    tag(ax, "(a)")

    # 各服务区往返里程
    ax = axes[1]
    mp = pd.read_csv(RES / "q1_max_payload.csv")
    d = mp[mp.gtype == "C"].sort_values("dist")
    x = np.arange(len(d))
    ax.bar(x, d["dist"] / 1000, color=PALETTE[3], width=0.62, alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(d["sid"], rotation=60, ha="right", fontsize=8.2)
    ax.set_ylabel("O01↔服务区 单程里程 / km")
    ax.set_title("各服务区单程里程", pad=8)
    for g, c in zip("ABC", [GCOLOR["A"], GCOLOR["B"], GCOLOR["C"]]):
        ax.axhline(GTS[g]["L0"] / 2000, color=c, ls="--", lw=1.3,
                   label=f'{GNAME[g]} 空载半航程')
    ax.legend(fontsize=8.2, loc="upper left")
    despine(ax)
    tag(ax, "(b)")
    save(fig, "q1_range_curve")


def fig_max_payload():
    """图：最大安全载荷热力图 + 约束类型分布。"""
    mp = pd.read_csv(RES / "q1_max_payload.csv")
    piv = mp.pivot(index="sid", columns="gtype", values="q_max")[["A", "B", "C"]]
    piv = piv.loc[sorted(piv.index)]
    fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.6),
                             gridspec_kw=dict(width_ratios=[1.55, 1]))
    ax = axes[0]
    im = ax.imshow(piv.values, cmap="YlGnBu", aspect="auto", vmin=0)
    ax.set_xticks(range(3)); ax.set_xticklabels([GNAME[g] for g in "ABC"])
    ax.set_yticks(range(len(piv))); ax.set_yticklabels(piv.index, fontsize=8.4)
    for i in range(piv.shape[0]):
        for j in range(3):
            v = piv.values[i, j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8.0,
                    color="white" if v > piv.values.max() * 0.6 else "#222")
    ax.set_title("各服务区–机型组合的最大安全载荷", pad=8)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, pad=0.02, fraction=0.045)
    cb.set_label("$q_{max}$ / kg", fontsize=9)
    tag(ax, "(a)")

    ax = axes[1]
    cnt = mp.groupby(["binding", "gtype"]).size().unstack(fill_value=0)
    cnt = cnt.reindex(columns=["A", "B", "C"], fill_value=0)
    bottom = np.zeros(len(cnt))
    for g in "ABC":
        ax.barh(cnt.index, cnt[g], left=bottom, color=GCOLOR[g],
                label=GNAME[g], height=0.55)
        bottom += cnt[g].to_numpy()
    ax.set_xlabel("服务区–机型组合数")
    ax.set_title("制约载荷的瓶颈约束", pad=8)
    ax.legend(fontsize=8.6)
    despine(ax)
    tag(ax, "(b)")
    save(fig, "q1_max_payload")


def fig_batching():
    """图：单点组批的机型对比（架次数 / 能耗 / 单位能耗）。"""
    s = pd.read_csv(RES / "q1_batching_summary.csv")
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.0))
    specs = [("n_trips", "架次数", "(a)"),
             ("total_energy", "总能耗 / kWh", "(b)"),
             ("energy_per_kg", "单位质量能耗 / (kWh·kg$^{-1}$)", "(c)")]
    for ax, (col, lab, tg) in zip(axes, specs):
        w = 0.26
        for k, g in enumerate("ABC"):
            d = s[s.gtype == g].set_index("sid").reindex(SIDS)
            ax.bar(np.arange(len(SIDS)) + (k - 1) * w, d[col], width=w,
                   color=GCOLOR[g], label=GNAME[g])
        ax.set_xticks(range(len(SIDS)))
        ax.set_xticklabels(SIDS, rotation=60, ha="right", fontsize=8.0)
        ax.set_ylabel(lab)
        ax.legend(fontsize=8.4)
        despine(ax); tag(ax, tg)
    save(fig, "q1_batching_compare")


def fig_pareto():
    """图：各服务区组批的 (架次数, 能耗) 帕累托前沿。"""
    par = pd.read_csv(RES / "q1_pareto_fronts.csv")
    s = pd.read_csv(RES / "q1_batching_summary.csv")
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    for g in "ABC":
        d = s[s.gtype == g]
        ax.scatter(d["n_trips"], d["total_energy"], s=34, color=GCOLOR[g],
                   alpha=0.42, edgecolor="none", label=f"{GNAME[g]}（全部单点方案）")
    if {"n_trips", "total_energy"} <= set(par.columns):
        p = par.sort_values("n_trips")
        ax.plot(p["n_trips"], p["total_energy"], "o-", color="#C44E52",
                lw=1.9, ms=6, zorder=6, label="帕累托前沿")
    # 逐服务区最优机型
    best = pd.read_csv(RES / "q1_best_per_sid.csv")
    key = "total_energy" if "total_energy" in best.columns else best.columns[-1]
    ax.scatter(best["n_trips"], best[key], marker="*", s=150,
               color="#222222", zorder=7, label="逐服务区最优机型")
    ax.set_xlabel("架次数")
    ax.set_ylabel("组批总能耗 / kWh")
    ax.legend(fontsize=8.6)
    despine(ax)
    save(fig, "q1_pareto")


def fig_rho():
    """图：返航安全余量 ρ 的灵敏度（热力图 + 折线）。"""
    r = pd.read_csv(RES / "q1_rho_sensitivity.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.2),
                             gridspec_kw=dict(width_ratios=[1.25, 1]))
    ax = axes[0]
    val = [c for c in r.columns if c not in ("rho", "gtype", "sid")][0]
    piv = r.pivot_table(index="gtype", columns="rho", values=val)
    piv = piv.reindex(["A", "B", "C"])
    im = ax.imshow(piv.values, cmap="magma_r", aspect="auto")
    ax.set_xticks(range(piv.shape[1]))
    ax.set_xticklabels([f"{c:.2f}" for c in piv.columns], fontsize=8.4)
    ax.set_yticks(range(3)); ax.set_yticklabels([GNAME[g] for g in "ABC"])
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            if not np.isnan(piv.values[i, j]):
                ax.text(j, i, f"{piv.values[i, j]:.1f}", ha="center",
                        va="center", fontsize=7.6, color="#111")
    ax.set_xlabel(r"返航安全余量比例 $\rho$")
    ax.set_title(f"$\\rho$ 对{val}的影响", pad=8)
    ax.grid(False)
    fig.colorbar(im, ax=ax, pad=0.02, fraction=0.045)
    tag(ax, "(a)")

    ax = axes[1]
    for g in "ABC":
        d = r[r.gtype == g].groupby("rho")[val].mean()
        ax.plot(d.index, d.values, "o-", color=GCOLOR[g], label=GNAME[g])
    ax.set_xlabel(r"返航安全余量比例 $\rho$")
    ax.set_ylabel(f"{val} 均值")
    ax.set_title(r"$\rho$ 灵敏度的机型差异", pad=8)
    ax.legend(fontsize=8.6)
    despine(ax); tag(ax, "(b)")
    save(fig, "q1_rho_sensitivity")


def fig_box_violin():
    """图：货箱质量/体积分布的小提琴图与箱线图叠加（分组）。"""
    b = load_boxes()
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.0))
    for ax, (col, lab, tg) in zip(axes, [("mass", "货箱质量 / kg", "(a)"),
                                         ("vol", "货箱体积 / m$^3$", "(b)")]):
        parts = ax.violinplot([b.loc[b["type"] == t, col].to_numpy()
                               for t in b["type"].unique()],
                              showextrema=False, widths=0.8)
        for i, pc in enumerate(parts["bodies"]):
            pc.set_facecolor(PALETTE[i]); pc.set_alpha(0.55)
        bp = ax.boxplot([b.loc[b["type"] == t, col].to_numpy()
                         for t in b["type"].unique()],
                        widths=0.22, patch_artist=True, showfliers=True,
                        medianprops=dict(color="#111", lw=1.4),
                        flierprops=dict(marker="o", ms=3, alpha=0.5))
        for pc in bp["boxes"]:
            pc.set_facecolor("white")
        ax.set_xticks(range(1, len(b["type"].unique()) + 1))
        ax.set_xticklabels(b["type"].unique(), fontsize=9)
        ax.set_ylabel(lab)
        ax.legend([Patch(facecolor=PALETTE[i], alpha=0.55)
                   for i in range(len(b["type"].unique()))],
                  list(b["type"].unique()), fontsize=8.2, loc="upper right")
        despine(ax); tag(ax, tg)
    save(fig, "q1_box_violin")


if __name__ == "__main__":
    fig_range_curve()
    fig_max_payload()
    fig_batching()
    fig_pareto()
    fig_rho()
    fig_box_violin()
    print("Q1 配图完成")
