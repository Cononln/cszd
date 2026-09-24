# -*- coding: utf-8 -*-
"""问题二配图：运输架次甘特、能量流向、电池占用、ALNS 收敛与机型画像。"""
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
from common.viz import sankey, radar, gantt_rows

apply_theme()
RES = Path(__file__).resolve().parents[2] / "results"
FIG = Path(__file__).resolve().parents[2] / "figures"

TRIPS = pd.read_csv(RES / "q2_transport_trips.csv")
DUSE = pd.read_csv(RES / "q2_drone_usage.csv")
BUSE = pd.read_csv(RES / "q2_battery_usage.csv")
BOX = pd.read_csv(RES / "q2_box_delivery.csv")
ALNS = pd.read_csv(RES / "q2_alns_convergence.csv")
J = json.loads((RES / "q2_results.json").read_text(encoding="utf-8"))
S = J["summary"]
MAKESPAN = float(S.get("makespan", TRIPS["end"].max()))


def _drone_order():
    """按 机型 A→B→C、同机型内编号 排序。"""
    d = DUSE.copy()
    d["gk"] = d["gtype"].map({"A": 0, "B": 1, "C": 2})
    return d.sort_values(["gk", "drone"])["drone"].tolist()


def fig_q2_gantt():
    """图：全部运输架次的无人机甘特图与逐箱交付时刻。"""
    order = _drone_order()
    ypos = {d: i for i, d in enumerate(order)}
    fig, ax = plt.subplots(figsize=(12.4, 6.0))
    for _, r in TRIPS.iterrows():
        y = ypos[r["drone"]]
        ax.barh(y, r["end"] - r["start"], left=r["start"], height=0.52,
                color=GCOLOR[r["gtype"]], edgecolor="white", linewidth=0.8,
                zorder=3)
        ax.text(r["start"] + 40, y, f'{r["stops"]}·{r["n_box"]}箱', va="center",
                ha="left", fontsize=6.6, color="white", zorder=5)
    # 逐箱交付时刻
    bx = BOX.merge(TRIPS[["trip_id", "drone"]], on="trip_id", how="left")
    ax.scatter(bx["deliver"], [ypos[d] for d in bx["drone"]], marker="|",
               s=90, color="#222222", linewidth=1.1, zorder=6,
               label="逐箱交付时刻")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, fontsize=8.2)
    ax.invert_yaxis()
    ax.set_ylim(len(order) - 0.32, -0.68)   # 底部留白带，专供图例，避免压住末行
    ax.set_xlabel("时间 / s")
    ax.set_xlim(-120, MAKESPAN + 260)
    ax.axvline(MAKESPAN, color="#C44E52", ls="--", lw=1.4, zorder=4,
               label=f"完工期 {MAKESPAN:.0f} s")
    ax.legend(handles=[Patch(facecolor=GCOLOR[g], label=GNAME[g]) for g in "ABC"]
              + [plt.Line2D([], [], marker="|", ls="none", color="#222222",
                            markeredgewidth=1.1, markersize=9, label="逐箱交付时刻"),
                 plt.Line2D([], [], ls="--", color="#C44E52", label=f"完工期 {MAKESPAN:.0f} s")],
              fontsize=8.4, ncol=2, loc="lower right")
    despine(ax)
    save(fig, "q2_gantt")


def fig_q2_energy_sankey():
    """图：运输能耗由机型流向服务区的桑基图。"""
    g_e = TRIPS.groupby("gtype")["energy"].sum().reindex(list("ABC"))
    s_e = TRIPS.groupby("stops")["energy"].sum().reindex(SIDS).fillna(0)
    left = [(GNAME[g], float(g_e[g]), GCOLOR[g]) for g in "ABC" if g_e[g] > 0]
    gi = {g: i for i, g in enumerate([g for g in "ABC" if g_e[g] > 0])}
    right, si = [], {}
    for k, s in enumerate(SIDS):
        if s_e[s] > 1e-9:
            si[s] = len(right)
            right.append((s, float(s_e[s]), PALETTE[k % len(PALETTE)]))
    fl = TRIPS.groupby(["gtype", "stops"])["energy"].sum().reset_index()
    flows = [(gi[r["gtype"]], si[r["stops"]], float(r["energy"]),
              GCOLOR[r["gtype"]]) for _, r in fl.iterrows()
             if r["gtype"] in gi and r["stops"] in si]
    fig, ax = plt.subplots(figsize=(9.6, 6.4))
    sankey(ax, left, right, flows, value_fmt="{:.1f}")
    ax.set_title("运输能耗的机型–服务区流向 / kWh", pad=6)
    save(fig, "q2_energy_sankey")


def fig_q2_battery():
    """图：共享电池的负载、最低荷电状态与充电占用。"""
    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.4),
                             gridspec_kw=dict(width_ratios=[1.35, 1]))
    ax = axes[0]
    b = BUSE.copy()
    b["gk"] = b["gtype"].map({"A": 0, "B": 1, "C": 2})
    b = b.sort_values(["gk", "battery"])
    x = np.arange(len(b))
    ax.bar(x, b["total_energy"], color=[GCOLOR[g] for g in b["gtype"]],
           width=0.66, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(b["battery"], rotation=0, fontsize=8.0)
    ax.set_ylabel("累计放电量 / kWh")
    ax.set_title("各电池组承担的运输能耗", pad=8)
    ax2 = ax.twinx()
    ax2.plot(x, b["min_soc"], "o-", color="#C44E52", lw=1.6, ms=5, zorder=5,
             label="最低 SoC")
    ax2.axhline(20, color="#8C8C8C", ls=":", lw=1.2)
    ax2.text(len(b) - 0.5, 21, "20% 下限", fontsize=7.6, color="#666666",
             ha="right")
    ax2.set_ylabel("最低荷电状态 / %", color="#C44E52")
    ax2.tick_params(axis="y", colors="#C44E52")
    ax2.grid(False)
    ax2.set_ylim(0, 105)
    despine(ax); tag(ax, "(a)")
    ax.legend(handles=[Patch(facecolor=GCOLOR[g], label=GNAME[g]) for g in "ABC"]
              + [plt.Line2D([], [], marker="o", color="#C44E52", ls="-",
                            label="最低 SoC")],
              fontsize=8.0, loc="upper left")

    ax = axes[1]
    for g in "ABC":
        d = BUSE[BUSE.gtype == g]
        ax.scatter(d["charge_total_s"] / 3600, d["n_trips"], s=95,
                   color=GCOLOR[g], edgecolor="white", linewidth=1.1,
                   label=GNAME[g], zorder=4)
    for _, r in BUSE.iterrows():
        ax.annotate(r["battery"], (r["charge_total_s"] / 3600, r["n_trips"]),
                    textcoords="offset points", xytext=(5, 3), fontsize=7.0,
                    color="#555555")
    ax.set_xlabel("累计充电时长 / h")
    ax.set_ylabel("电池组承担架次数")
    ax.set_title("充电占用与架次分配", pad=8)
    ax.legend(fontsize=8.4)
    despine(ax); tag(ax, "(b)")
    save(fig, "q2_battery")


def fig_q2_alns():
    """图：ALNS 迭代收敛过程（四个目标分量）。"""
    fig, axes = plt.subplots(1, 4, figsize=(14.0, 3.5))
    specs = [("obj", "加权目标值", "#4C72B0"),
             ("n_trips", "架次数", "#DD8452"),
             ("energy", "运输能耗 / kWh", "#55A868"),
             ("makespan", "完工期 / s", "#C44E52")]
    for ax, (col, lab, c) in zip(axes, specs):
        y = ALNS[col].to_numpy(dtype=float)
        ax.plot(ALNS["iter"], y, color=c, lw=1.5, alpha=0.85)
        run = np.minimum.accumulate(y)
        ax.plot(ALNS["iter"], run, color="#222222", lw=1.9,
                label="历史最优" if col == "obj" else None)
        ax.set_xlabel("迭代次数")
        ax.set_ylabel(lab)
        ax.set_title(lab, pad=7)
        despine(ax)
    axes[0].legend(fontsize=8.2)
    save(fig, "q2_alns_convergence")


def fig_q2_concurrency():
    """图：在飞无人机数量与累计交付箱数的时序。"""
    ev = []
    for _, r in TRIPS.iterrows():
        ev.append((r["start"], 1))
        ev.append((r["end"], -1))
    ev.sort()
    t, cur, ts, cs = 0.0, 0, [], []
    for tt, d in ev:
        ts.append(tt); cs.append(cur)
        cur += d
        ts.append(tt); cs.append(cur)
    bx = BOX.sort_values("deliver")
    fig, ax = plt.subplots(figsize=(11.4, 4.3))
    ax.fill_between(ts, cs, step="post", color="#4C72B0", alpha=0.30, zorder=2)
    ax.step(ts, cs, where="post", color="#4C72B0", lw=1.7, zorder=3,
            label="在飞无人机数")
    fleet = int(DUSE.shape[0])
    ax.axhline(fleet, color="#C44E52", ls="--", lw=1.4, zorder=4,
               label=f"机队规模 {fleet} 架（并行上限）")
    ax.set_ylim(0, fleet + 1.1)
    ax.set_xlabel("时间 / s")
    ax.set_ylabel("在飞无人机数 / 架")
    ax.set_xlim(0, MAKESPAN * 1.02)
    ax2 = ax.twinx()
    ax2.plot(bx["deliver"], np.arange(1, len(bx) + 1), color="#55A868", lw=2.0,
             label="累计交付箱数")
    ax2.set_ylabel("累计交付箱数 / 箱", color="#55A868")
    ax2.tick_params(axis="y", colors="#55A868")
    ax2.set_ylim(0, len(bx) * 1.05)
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8.4, loc="upper left")
    despine(ax); tag(ax, "")
    save(fig, "q2_concurrency")


def fig_q2_drone_util():
    """图：单机时间利用率与载重利用率。"""
    d = DUSE.copy()
    d["gk"] = d["gtype"].map({"A": 0, "B": 1, "C": 2})
    d = d.sort_values(["gk", "drone"]).reset_index(drop=True)
    x = np.arange(len(d))
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.2),
                             gridspec_kw=dict(width_ratios=[1.6, 1]))
    ax = axes[0]
    busy_h = d["busy_s"] / 3600.0
    ax.bar(x, busy_h, color=[GCOLOR[g] for g in d["gtype"]], width=0.62,
           zorder=3, label="在飞时长")
    ax.bar(x, MAKESPAN / 3600.0 - busy_h, bottom=busy_h, color="#E8E8E8",
           width=0.62, zorder=2, label="空闲时长")
    for i, r in d.iterrows():
        ax.text(i, busy_h[i] + 0.06, f'{r["n_trips"]}', ha="center",
                fontsize=7.4, color="#444444")
    ax.set_xticks(x); ax.set_xticklabels(d["drone"], fontsize=8.0)
    ax.set_ylabel("时间 / h")
    ax.set_title("单机时间利用率（数字为架次数）", pad=8)
    ax.legend(fontsize=8.4, loc="upper left")
    despine(ax); tag(ax, "(a)")

    ax = axes[1]
    t = TRIPS.copy()
    t["Q"] = t["gtype"].map(lambda g: GTS[g]["Q"])
    t["load"] = t["mass"] / t["Q"] * 100
    grp = [t.loc[t.gtype == g, "load"].to_numpy() for g in "ABC"]
    parts = ax.violinplot(grp, showextrema=False, widths=0.85)
    for pc, g in zip(parts["bodies"], "ABC"):
        pc.set_facecolor(GCOLOR[g]); pc.set_alpha(0.42)
    bp = ax.boxplot(grp, widths=0.20, patch_artist=True, showfliers=True,
                    medianprops=dict(color="#111", lw=1.4),
                    flierprops=dict(marker="o", ms=3.4, alpha=0.55))
    for pc in bp["boxes"]:
        pc.set_facecolor("white")
    ax.set_xticks([1, 2, 3]); ax.set_xticklabels([GNAME[g] for g in "ABC"])
    ax.set_ylabel("单架次载重利用率 / %")
    ax.set_title("载重利用率分布", pad=8)
    despine(ax); tag(ax, "(b)")
    save(fig, "q2_drone_util")


def fig_q2_radar():
    """图：三类机型的多维画像雷达图。"""
    rows = []
    for g in "ABC":
        t = TRIPS[TRIPS.gtype == g]
        d = DUSE[DUSE.gtype == g]
        rows.append(dict(
            gtype=g,
            trips=len(t),
            energy=t["energy"].sum(),
            load=(t["mass"] / GTS[g]["Q"] * 100).mean() / 100.0,
            busy=d["busy_s"].sum() / (len(d) * MAKESPAN),
            per_kg=t["energy"].sum() / max(t["mass"].sum(), 1e-9)))
    r = pd.DataFrame(rows).set_index("gtype").reindex(list("ABC"))

    def norm(col, benefit):
        v = r[col].to_numpy(float)
        lo, hi = v.min(), v.max()
        z = np.full_like(v, 0.5) if hi - lo < 1e-12 else (v - lo) / (hi - lo)
        return z if benefit else 1.0 - z

    mat = np.vstack([
        norm("trips", False),
        norm("energy", False),
        norm("load", True),
        norm("busy", True),
        norm("per_kg", False),
    ]).T
    labels = ["架次数\n(少为优)", "总能耗\n(少为优)", "载重利用率", "时间利用率",
              "单位质量能耗\n(少为优)"]
    fig, ax = plt.subplots(figsize=(5.6, 5.2), subplot_kw=dict(polar=True))
    radar(ax, labels, [(GNAME[g], mat[i]) for i, g in enumerate("ABC")],
          [GCOLOR[g] for g in "ABC"])
    ax.legend(fontsize=8.6, loc="upper right", bbox_to_anchor=(1.24, 1.12))
    save(fig, "q2_radar")


if __name__ == "__main__":
    fig_q2_gantt()
    fig_q2_energy_sankey()
    fig_q2_battery()
    fig_q2_alns()
    fig_q2_concurrency()
    fig_q2_drone_util()
    fig_q2_radar()
    print("Q2 配图完成")
