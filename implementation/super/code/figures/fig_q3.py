# -*- coding: utf-8 -*-
"""问题三配图：中断区间、中继调度甘特、覆盖网络、悬停点地理分布与机队规模权衡。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.style import (GCOLOR, GNAME, MODE_COLOR, PALETTE, save, despine,
                          tag, apply_theme)
from common.route import NODES, SIDS
from common.viz import pareto_mask

apply_theme()
RES = Path(__file__).resolve().parents[2] / "results"

CS = pd.read_csv(RES / "q3_comm_support.csv")
CS.columns = ["trip_id", "phase", "t0", "t1", "mode", "relay_id"]
OUT = pd.read_csv(RES / "q3_outage_segments.csv")
REL = pd.read_csv(RES / "q3_relay_trips.csv")
REL.columns = ["relay_id", "relay_drone", "module", "start", "lon", "lat",
               "alt", "link_t", "serv_end", "back_t", "energy"]
FSZ = pd.read_csv(RES / "q3_fleet_sizing.csv")
HOV = pd.read_csv(RES / "q3_hover_candidates.csv")
TRIPS = pd.read_csv(RES / "q2_transport_trips.csv")
J = json.loads((RES / "q3_results.json").read_text(encoding="utf-8"))
S = J["summary"]
MAKESPAN = float(S["makespan"])


def _trip_order():
    """按服务区编号排序运输架次，使同服务区的架次相邻。"""
    t = TRIPS[["trip_id", "stops"]].copy()
    return t.sort_values(["stops", "trip_id"])["trip_id"].tolist()


def fig_q3_outage_timeline():
    """图：各运输架次的通信保障时段与中断区间。"""
    order = _trip_order()
    y = {t: i for i, t in enumerate(order)}
    fig, ax = plt.subplots(figsize=(12.6, 7.0))
    for _, r in CS.iterrows():
        if r["trip_id"] not in y:
            continue
        ax.barh(y[r["trip_id"]], r["t1"] - r["t0"], left=r["t0"], height=0.5,
                color=MODE_COLOR[r["mode"]], edgecolor="white", linewidth=0.5,
                zorder=3)
    for _, r in OUT.iterrows():
        if r["trip_id"] not in y:
            continue
        yy = y[r["trip_id"]]
        covered = pd.notna(r["relay_trip_id"])
        ax.barh(yy, r["dur"], left=r["t0"], height=0.74,
                color="none", edgecolor="#C44E52",
                hatch="" if covered else "///", linewidth=1.3, zorder=5)
        ax.plot([r["t0"], r["t1"]], [yy - 0.42, yy - 0.42], lw=2.0,
                color="#55A868" if covered else "#C44E52", zorder=6,
                solid_capstyle="butt")
    # 中继架次各自占一行：三架次时段高度重叠，画在同一行会互相遮盖
    ry = [-1.15 - 0.46 * i for i in range(len(REL))]
    for yy, (_, r) in zip(ry, REL.iterrows()):
        ax.barh(yy, r["back_t"] - r["start"], left=r["start"], height=0.40,
                color="#8172B3", edgecolor="white", linewidth=0.6, zorder=3)
        ax.text(r["start"] + 30, yy, r["relay_id"], va="center", ha="left",
                fontsize=7.0, color="white", zorder=5)
    ax.set_yticks(list(range(len(order))) + ry)
    ax.set_yticklabels(order + REL["relay_id"].tolist(), fontsize=7.6)
    ax.set_ylim(len(order) - 0.3, min(ry) - 0.45)
    ax.set_xlim(-120, MAKESPAN + 200)
    ax.set_xlabel("时间 / s")
    ax.legend(handles=[Patch(facecolor=MODE_COLOR["直连"], label="直连保障"),
                       Patch(facecolor=MODE_COLOR["中继"], label="中继保障"),
                       Patch(facecolor="none", edgecolor="#C44E52",
                             label="中断区间（红框）"),
                       Patch(facecolor="#8172B3", label="中继架次")],
              fontsize=8.4, ncol=4, loc="lower center",
              bbox_to_anchor=(0.5, -0.145), frameon=False)
    despine(ax)
    save(fig, "q3_outage_timeline")


def fig_q3_relay_detail():
    """图：三架中继无人机的建链、悬停服务与返航时序。"""
    fig, ax = plt.subplots(figsize=(11.6, 3.5))
    for i, (_, r) in enumerate(REL.iterrows()):
        ax.barh(i, r["link_t"] - r["start"], left=r["start"], height=0.46,
                color="#B0B0B0", edgecolor="white", linewidth=0.7, zorder=3)
        ax.barh(i, r["serv_end"] - r["link_t"], left=r["link_t"], height=0.46,
                color="#8172B3", edgecolor="white", linewidth=0.7, zorder=3)
        ax.barh(i, r["back_t"] - r["serv_end"], left=r["serv_end"],
                height=0.46, color="#DD8452", edgecolor="white",
                linewidth=0.7, zorder=3)
        ax.text(r["start"] + 40, i - 0.42,
                f'{r["relay_drone"]}·{r["module"]}·{r["energy"]:.2f} kWh',
                fontsize=7.6, color="#444444", va="top")
    ax.set_yticks(range(len(REL)))
    ax.set_yticklabels(REL["relay_id"], fontsize=8.4)
    ax.invert_yaxis()
    ax.set_ylim(len(REL) - 0.25, -1.35)
    ax.set_xlabel("时间 / s")
    ax.legend(handles=[Patch(facecolor="#B0B0B0", label="起飞→建链"),
                       Patch(facecolor="#8172B3", label="悬停中继服务"),
                       Patch(facecolor="#DD8452", label="返航")],
              fontsize=8.4, ncol=3, loc="lower center",
              bbox_to_anchor=(0.5, -0.30), frameon=False)
    despine(ax)
    save(fig, "q3_relay_detail")


def fig_q3_coverage_heatmap():
    """图：中断区间—中继架次覆盖矩阵。"""
    o = OUT.sort_values(["trip_id", "t0"]).reset_index(drop=True)
    rl = REL["relay_id"].tolist()
    M = np.zeros((len(o), len(rl)))
    for i, r in o.iterrows():
        if pd.notna(r["relay_trip_id"]) and r["relay_trip_id"] in rl:
            M[i, rl.index(r["relay_trip_id"])] = r["dur"]
    fig, ax = plt.subplots(figsize=(4.6, 7.4))
    im = ax.imshow(M, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(rl))); ax.set_xticklabels(rl, fontsize=8.4)
    ax.set_yticks(range(len(o)))
    ax.set_yticklabels([f'{r["trip_id"]}' for _, r in o.iterrows()], fontsize=7.0)
    for i in range(len(o)):
        for j in range(len(rl)):
            if M[i, j] > 0:
                ax.text(j, i, f"{M[i, j]:.0f}", ha="center", va="center",
                        fontsize=6.6, color="#222222")
    ax.set_xlabel("中继架次")
    ax.set_ylabel("中断区间所属运输架次")
    ax.grid(False)
    fig.colorbar(im, ax=ax, pad=0.03, fraction=0.05).set_label("覆盖时长 / s",
                                                               fontsize=8.6)
    save(fig, "q3_coverage_heatmap")


def fig_q3_network():
    """图：中继架次与运输架次的中继保障二分网络。"""
    import networkx as nx
    G = nx.Graph()
    agg = OUT.dropna(subset=["relay_trip_id"]).groupby(
        ["relay_trip_id", "trip_id"])["dur"].sum().reset_index()
    rl = REL["relay_id"].tolist()
    for r in rl:
        G.add_node(r, kind="relay")
    for _, r in agg.iterrows():
        G.add_node(r["trip_id"], kind="trip")
        G.add_edge(r["relay_trip_id"], r["trip_id"], w=float(r["dur"]))
    # 中继机放左侧一列，运输架次放右侧一列并按时段排序
    tp = [n for n in G.nodes if G.nodes[n]["kind"] == "trip"]
    t_order = OUT.groupby("trip_id")["t0"].min().reindex(tp).sort_values().index.tolist()
    pos = {}
    for i, r in enumerate(rl):
        pos[r] = (0.0, i - (len(rl) - 1) / 2)
    for i, t in enumerate(t_order):
        pos[t] = (1.35, i - (len(t_order) - 1) / 2)
    fig, ax = plt.subplots(figsize=(7.0, 7.6))
    for u, v, d in G.edges(data=True):
        ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                color="#DD8452", lw=0.8 + d["w"] / 900, alpha=0.55, zorder=2)
    nx.draw_networkx_nodes(G, pos, nodelist=rl, ax=ax, node_size=760,
                           node_color="#8172B3", edgecolors="white",
                           linewidths=1.4, node_shape="s")
    nx.draw_networkx_nodes(G, pos, nodelist=t_order, ax=ax, node_size=380,
                           node_color="#4C72B0", edgecolors="white",
                           linewidths=1.2)
    nx.draw_networkx_labels(G, pos, {r: r for r in rl}, ax=ax, font_size=8.0,
                            font_color="white")
    nx.draw_networkx_labels(G, pos, {t: t.replace("Q2-", "") for t in t_order},
                            ax=ax, font_size=6.6, font_color="white")
    ax.axis("off")
    ax.set_title("中继架次–运输架次保障关系", pad=6)
    save(fig, "q3_network")


def fig_q3_hover_map():
    """图：中继悬停候选点的可回传性与最终选址。"""
    ok = HOV[HOV["backhaul_ok"]]
    no = HOV[~HOV["backhaul_ok"]]
    fig, ax = plt.subplots(figsize=(8.0, 6.4))
    ax.scatter(no["lon"], no["lat"], s=5, color="#CCCCCC", alpha=0.75,
               label=f"不可回传（{len(no)} 点）", zorder=2)
    ax.scatter(ok["lon"], ok["lat"], s=6, color="#55A868", alpha=0.55,
               label=f"满足回传约束（{len(ok)} 点）", zorder=3)
    ax.scatter(NODES.loc[SIDS, "lon"], NODES.loc[SIDS, "lat"], s=26,
               color="#4C72B0", marker="o", edgecolor="white", linewidth=0.8,
               label="服务区", zorder=4)
    ax.scatter(NODES.loc["O01", "lon"], NODES.loc["O01", "lat"], s=170,
               color="#C44E52", marker="*", edgecolor="white", linewidth=1.0,
               label="O01 基地", zorder=6)
    ax.scatter(REL["lon"], REL["lat"], s=185, marker="X", color="#8172B3",
               edgecolor="white", linewidth=1.3, label="中继悬停点", zorder=7)
    for _, r in REL.iterrows():
        ax.annotate(r["relay_id"], (r["lon"], r["lat"]),
                    textcoords="offset points", xytext=(7, -2), fontsize=8.0,
                    color="#8172B3")
    for s in SIDS:
        ax.annotate(s, (NODES.loc[s, "lon"], NODES.loc[s, "lat"]),
                    textcoords="offset points", xytext=(4, 3), fontsize=6.4,
                    color="#666666")
    ax.set_xlabel("经度 / °")
    ax.set_ylabel("纬度 / °")
    ax.legend(fontsize=8.0, loc="upper left", framealpha=0.94)
    despine(ax)
    save(fig, "q3_hover_map")


def fig_q3_fleet_sizing():
    """图：中继无人机数量对覆盖完整性与能耗的影响。"""
    f = FSZ.sort_values("n_relay_drones")
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    x = np.arange(len(f))
    ax.bar(x, f["uncovered_s"] / 60.0, color="#C44E52", width=0.5, alpha=0.88,
           zorder=3, label="未覆盖中断时长")
    for i, v in enumerate(f["uncovered_s"] / 60.0):
        ax.text(i, v + 2, f"{v:.0f} min", ha="center", fontsize=8.4,
                color="#C44E52")
    ax.set_xticks(x)
    ax.set_xticklabels([f'{int(n)} 架' for n in f["n_relay_drones"]], fontsize=9.5)
    ax.set_xlabel("配备中继无人机数量")
    ax.set_ylabel("未覆盖中断时长 / min", color="#C44E52")
    ax.tick_params(axis="y", colors="#C44E52")
    ax.set_ylim(0, (f["uncovered_s"] / 60.0).max() * 1.30)
    ax2 = ax.twinx()
    ax2.plot(x, f["relay_energy"], "o-", color="#8172B3", lw=2.0, ms=8,
             zorder=5, label="中继总能耗")
    ax2.plot(x, f["n_relay_trips"], "s--", color="#DD8452", lw=1.7, ms=7,
             zorder=5, label="中继架次数")
    for i, v in enumerate(f["relay_energy"]):
        ax2.annotate(f"{v:.2f} kWh", (i, v), textcoords="offset points",
                     xytext=(0, 9), ha="center", fontsize=8.0, color="#8172B3")
    ax2.set_ylabel("中继能耗 / kWh  ·  架次数")
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8.6, loc="upper center")
    despine(ax)
    save(fig, "q3_fleet_sizing")


def fig_q3_energy_donut():
    """图：运输能耗与中继能耗的构成。"""
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.3))
    ax = axes[0]
    e = TRIPS.groupby("gtype")["energy"].sum().reindex(list("ABC")).fillna(0)
    rel = float(S["relay_energy"])
    vals = [e["A"], e["B"], e["C"], rel]
    labs = [f"{GNAME['A']} 运输", f"{GNAME['B']} 运输", f"{GNAME['C']} 运输",
            "中继机"]
    cols = [GCOLOR["A"], GCOLOR["B"], GCOLOR["C"], "#8172B3"]
    w, _, at = ax.pie(vals, colors=cols, startangle=90, counterclock=False,
                      autopct=lambda p: f"{p:.1f}%", pctdistance=0.78,
                      wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.4),
                      textprops=dict(fontsize=8.4))
    ax.text(0, 0.10, f'{sum(vals):.2f}', ha="center", va="center", fontsize=15)
    ax.text(0, -0.16, "总能耗 / kWh", ha="center", va="center", fontsize=8.4,
            color="#666666")
    ax.legend(w, labs, fontsize=8.2, loc="center left",
              bbox_to_anchor=(0.96, 0.5))
    tag(ax, "(a)")

    ax = axes[1]
    n = CS.groupby("mode").size().reindex(["直连", "中继"]).fillna(0)
    dur = CS.groupby("mode").apply(
        lambda d: (d["t1"] - d["t0"]).sum(), include_groups=False
    ).reindex(["直连", "中继"]).fillna(0)
    x = np.arange(2)
    ax.bar(x - 0.19, n.values, width=0.36, color="#4C72B0", zorder=3,
           label="保障阶段数")
    ax2 = ax.twinx()
    ax2.bar(x + 0.19, dur.values / 60.0, width=0.36, color="#DD8452", zorder=3,
            label="保障时长")
    for i in range(2):
        ax.text(i - 0.19, n.values[i] + 1, f"{n.values[i]:.0f}", ha="center",
                fontsize=8.4)
        ax2.text(i + 0.19, dur.values[i] / 60.0 + 1, f"{dur.values[i]/60:.0f}",
                 ha="center", fontsize=8.4, color="#DD8452")
    ax.set_xticks(x); ax.set_xticklabels(["直连", "中继"])
    ax.set_ylabel("保障阶段数", color="#4C72B0")
    ax2.set_ylabel("保障时长 / min", color="#DD8452")
    ax2.grid(False)
    ax.set_ylim(0, n.values.max() * 1.22)
    ax2.set_ylim(0, dur.values.max() / 60.0 * 1.22)
    tag(ax, "(b)")
    save(fig, "q3_energy_donut")


if __name__ == "__main__":
    fig_q3_outage_timeline()
    fig_q3_relay_detail()
    fig_q3_coverage_heatmap()
    fig_q3_network()
    fig_q3_hover_map()
    fig_q3_fleet_sizing()
    fig_q3_energy_donut()
    print("Q3 配图完成")
