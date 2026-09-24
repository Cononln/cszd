# -*- coding: utf-8 -*-
"""为 p3/p4 增强方案生成论文级静态可视化。

说明：本脚本只读取各 pro 方案已经生成的 csv，不改变任何求解代码和原始结果。
输出到各方案目录下的 figures_plus 文件夹，便于与原有 figures 对照。
"""
from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent
plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "font.size": 10,
    "axes.titlesize": 14,
    "axes.labelsize": 10,
    "figure.dpi": 120,
    "savefig.dpi": 230,
})
BG, GRID, TEXT = "#f7f8fa", "#dfe4ea", "#243447"
BLUE, TEAL, ORANGE, RED, PURPLE = "#2f6fed", "#10a38c", "#f39c4a", "#df5d67", "#7856c7"
PALETTE = [BLUE, TEAL, ORANGE, PURPLE, RED, "#4c9fbf"]


def setup_ax(ax, grid="y"):
    ax.set_facecolor(BG)
    ax.tick_params(colors="#586574", labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#bdc6d0")
        ax.spines[s].set_linewidth(.8)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=.8, alpha=.9)
        ax.set_axisbelow(True)
    ax.set_xlabel(ax.get_xlabel(), color=TEXT)
    ax.set_ylabel(ax.get_ylabel(), color=TEXT)


def save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.patch.set_facecolor(BG)
    fig.tight_layout(pad=1.3)
    fig.savefig(path, facecolor=BG, bbox_inches="tight")
    plt.close(fig)


def read_csv(folder, name):
    return pd.read_csv(folder / name, encoding="utf-8-sig")


def parse_stops(seq):
    return [x for x in str(seq).split("->") if x]


def load_geo():
    from q00 import load_nodes
    return load_nodes()


def p3_visuals(tag):
    base = ROOT / tag
    out = base / "outputs"
    figdir = base / "figures_plus"
    routes = read_csv(out, f"{tag}_routes.csv")
    states = read_csv(out, f"{tag}_communication_states.csv")
    relay = read_csv(out, f"{tag}_relay_schedule.csv")
    timeline_path = out / f"{tag}_resource_timeline.csv"
    timeline = pd.read_csv(timeline_path, encoding="utf-8-sig") if timeline_path.exists() else pd.DataFrame()
    boxes = read_csv(out, f"{tag}_box_delivery.csv")
    o01, services = load_geo()
    coords = {"O01": (float(o01["经度"]), float(o01["纬度"]))}
    coords.update({str(r["服务区编号"]): (float(r["经度"]), float(r["纬度"])) for _, r in services.iterrows()})

    # 1. 路线—中继联合地图：箭头表达访问方向，颜色表达机型。
    fig, ax = plt.subplots(figsize=(11, 8))
    drone_colors = {"A": BLUE, "B": TEAL, "C": ORANGE}
    for _, r in routes.iterrows():
        pts = [coords.get(s) for s in parse_stops(r["停靠序列"]) if s in coords]
        if len(pts) < 2:
            continue
        c = drone_colors.get(str(r["机型编号"]), PURPLE)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=c, alpha=.26, lw=1.2)
        for a, b in zip(pts[:-1], pts[1:]):
            ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", color=c, alpha=.46, lw=.7))
    ax.scatter([o01["经度"]], [o01["纬度"]], s=210, marker="s", color="#18212b", zorder=5, label="O01/G01")
    ax.scatter(services["经度"], services["纬度"], s=58, color="#778392", edgecolors="white", linewidth=.7, zorder=4, label="服务区")
    for _, s in services.iterrows():
        ax.text(s["经度"] + .0004, s["纬度"] + .00025, str(s["服务区编号"]), fontsize=8, color=TEXT)
    rp = routes[routes["是否需要中继"].astype(bool)].copy()
    if not rp.empty:
        rp = rp.drop_duplicates(subset=["路线编号"])
        ax.scatter(rp["中继经度"], rp["中继纬度"],
                   marker="^", s=105, color=RED, edgecolors="white", linewidth=.8, zorder=6, label="中继悬停点")
    ax.set_title(f"{tag} 运输路线与通信中继布局", loc="left", fontweight="bold", color=TEXT)
    ax.set_xlabel("经度"); ax.set_ylabel("纬度"); setup_ax(ax, "both")
    ax.legend(frameon=False, ncol=4, loc="upper right")
    save(fig, figdir / f"{tag}_plus01_路线中继箭头地图.png")

    # 2. 通信状态热图：横轴为路线内相对进度，颜色表达直连/中继/中断。
    order = routes["路线编号"].astype(str).tolist()
    pivot = states.pivot_table(index="路线编号", columns="采样点序号", values="通信状态", aggfunc="first").reindex(order)
    code = {"直连": 0, "中继": 1, "中断": 2}
    mat = pivot.apply(lambda col: col.map(lambda x: code.get(x, np.nan))).to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(12, max(5.5, .19 * len(order) + 2)))
    cmap = ListedColormap(["#8bd3c7", "#f5b66a", "#df5d67"])
    im = ax.imshow(mat, aspect="auto", interpolation="nearest", cmap=cmap, vmin=0, vmax=2)
    ax.set_yticks(np.arange(len(order))); ax.set_yticklabels(order)
    ax.set_xlabel("架次内相对通信进度"); ax.set_ylabel("路线编号")
    ax.set_title(f"{tag} 连续通信状态热图", loc="left", fontweight="bold", color=TEXT)
    ax.set_xticks(np.linspace(0, max(1, mat.shape[1] - 1), 5).astype(int))
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"][:len(ax.get_xticks())])
    ax.grid(False)
    ax.legend(handles=[Patch(color="#8bd3c7", label="直连"), Patch(color="#f5b66a", label="中继"), Patch(color="#df5d67", label="中断")], frameon=False, ncol=3, loc="upper right")
    save(fig, figdir / f"{tag}_plus02_通信状态热图.png")

    # 3. 资源调度甘特图：运输与中继资源分层显示。
    fig, ax = plt.subplots(figsize=(12, 7))
    tl = timeline.copy()
    if not tl.empty:
        resources = list(dict.fromkeys(tl["资源编号"].astype(str)))
        y = {x: i for i, x in enumerate(resources)}
        for _, r in tl.iterrows():
            start, end = float(r["开始_s"]) / 3600, float(r["结束_s"]) / 3600
            c = BLUE if str(r["资源类型"]) == "运输无人机" else RED
            ax.barh(y[str(r["资源编号"])], max(0, end - start), left=start, height=.62, color=c, alpha=.86)
            if end - start > .35:
                ax.text(start + (end - start) / 2, y[str(r["资源编号"])], str(r["任务编号"]), ha="center", va="center", fontsize=7, color="white")
        ax.set_yticks(range(len(resources))); ax.set_yticklabels(resources)
    ax.set_xlabel("绝对时间 (h)"); ax.set_ylabel("资源")
    ax.set_title(f"{tag} 运输—中继资源调度时序", loc="left", fontweight="bold", color=TEXT)
    setup_ax(ax, "x")
    ax.legend(handles=[Patch(color=BLUE, label="运输无人机"), Patch(color=RED, label="中继无人机")], frameon=False, ncol=2)
    save(fig, figdir / f"{tag}_plus03_资源调度甘特图.png")

    # 4. 路线效率散点：能耗与执行时间，气泡大小表示中继需求。
    fig, ax = plt.subplots(figsize=(9, 6))
    x = routes["路线时间_s"].astype(float) / 60
    yv = routes["路线能耗_kWh"].astype(float)
    size = 35 + routes["是否需要中继"].astype(bool).astype(int) * 80
    for typ, g in routes.groupby("机型编号"):
        ax.scatter(g["路线时间_s"] / 60, g["路线能耗_kWh"], s=size.loc[g.index], color=drone_colors.get(str(typ), PURPLE), alpha=.78, edgecolors="white", linewidth=.7, label=f"机型 {typ}")
    ax.set_xlabel("路线时间 (min)"); ax.set_ylabel("路线能耗 (kWh)")
    ax.set_title(f"{tag} 路线时间—能耗效率分布", loc="left", fontweight="bold", color=TEXT)
    setup_ax(ax, "both"); ax.legend(frameon=False)
    save(fig, figdir / f"{tag}_plus04_路线效率散点.png")

    # 5. 逐箱时限达成：按偏差排序，直接突出提前/延迟。
    if not boxes.empty:
        boxes = boxes.copy()
        # 货箱期望时刻需从原始清单读取；若输出没有该列，则用预测时刻排序展示。
        boxes["预测送达_h"] = boxes["预测送达_s"].astype(float) / 3600
        boxes = boxes.sort_values("预测送达_h").reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(12, 5.8))
        ax.plot(np.arange(len(boxes)), boxes["预测送达_h"], color=BLUE, lw=1.6, marker="o", ms=3.5, label="预测送达")
        ax.fill_between(np.arange(len(boxes)), 0, boxes["预测送达_h"], color=BLUE, alpha=.08)
        ax.set_xlabel("货箱（按预测送达时刻排序）"); ax.set_ylabel("送达时刻 (h)")
        ax.set_title(f"{tag} 逐箱送达时刻与任务进度", loc="left", fontweight="bold", color=TEXT)
        setup_ax(ax, "y"); ax.legend(frameon=False)
        save(fig, figdir / f"{tag}_plus05_逐箱送达进度.png")

    # 6. 中继服务负载：按中继点统计服务次数、平均通信覆盖率。
    if not rp.empty:
        stat = routes.assign(中继点=routes["中继点"].astype(str)).groupby("中继点").agg(服务次数=("路线编号", "count"), 平均覆盖率=("覆盖率", "mean")).sort_values("服务次数", ascending=False).head(12)
        fig, ax = plt.subplots(figsize=(10, 5.5))
        bars = ax.bar(stat.index, stat["服务次数"], color=TEAL, alpha=.9)
        ax.set_ylabel("服务路线数"); ax.set_xlabel("中继点")
        ax.set_title(f"{tag} 中继点服务负载", loc="left", fontweight="bold", color=TEXT)
        setup_ax(ax, "y")
        for b, v in zip(bars, stat["服务次数"]): ax.text(b.get_x() + b.get_width()/2, v + .1, f"{int(v)}", ha="center", fontsize=8)
        save(fig, figdir / f"{tag}_plus06_中继点负载.png")

    # 7. p3-4pro 的多情景鲁棒性对比。
    scenario_path = out / f"{tag}_scenario_evaluation.csv"
    if scenario_path.exists():
        sc = pd.read_csv(scenario_path, encoding="utf-8-sig")
        fig, ax1 = plt.subplots(figsize=(10, 5.6))
        xx = np.arange(len(sc))
        b = ax1.bar(xx - .18, sc["通信中断_s"], width=.36, color=RED, alpha=.88, label="通信中断 (s)")
        ax1.set_ylabel("通信中断 (s)"); ax1.set_xticks(xx, sc["情景"]); setup_ax(ax1, "y")
        ax2 = ax1.twinx(); ax2.plot(xx + .18, sc["中继架次"], color=BLUE, marker="o", lw=2, label="中继架次")
        ax2.set_ylabel("中继架次"); ax2.spines["top"].set_visible(False); ax2.grid(False)
        ax1.set_title(f"{tag} 链路损耗情景下的鲁棒性", loc="left", fontweight="bold", color=TEXT)
        for rect, val in zip(b, sc["通信中断_s"]): ax1.text(rect.get_x()+rect.get_width()/2, rect.get_height()+max(sc["通信中断_s"].max(), 1)*.03, f"{val:.0f}", ha="center", fontsize=8)
        h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels(); ax1.legend(h1+h2, l1+l2, frameon=False, loc="upper left")
        save(fig, figdir / f"{tag}_plus07_链路损耗鲁棒性.png")


def p4_visuals(tag, source_plan):
    base = ROOT / tag
    out = base / "outputs"
    figdir = base / "figures_plus"
    o01, services = load_geo()
    cmp = read_csv(out, f"{tag}_comparison.csv")
    part = {k: read_csv(out, f"{tag}_partition_K{k}.csv") for k in (2, 3)}
    work = {k: read_csv(out, f"{tag}_workload_K{k}.csv") for k in (2, 3)}
    res = {k: read_csv(out, f"{tag}_resources_K{k}.csv") for k in (2, 3)}

    # 1. 2组/3组分区地图。
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2), sharex=True, sharey=True)
    for ax, k in zip(axes, (2, 3)):
        d = part[k]; group = {}
        for _, r in d.iterrows():
            for s in str(r["服务区列表"]).replace("、", ",").split(","):
                group[s.strip()] = int(r["任务组"])
        for _, s in services.iterrows():
            g = group.get(str(s["服务区编号"]), 1) - 1
            ax.scatter(s["经度"], s["纬度"], s=100, color=PALETTE[g], edgecolors="white", linewidth=.8, zorder=4)
            ax.text(s["经度"] + .00035, s["纬度"] + .0002, str(s["服务区编号"]), fontsize=8, color=TEXT)
        ax.scatter([o01["经度"]], [o01["纬度"]], s=170, marker="s", color="#18212b", zorder=5)
        ax.set_title(f"{k}组任务分区", fontweight="bold", color=TEXT)
        ax.set_xlabel("经度"); ax.set_ylabel("纬度"); setup_ax(ax, "both")
        ax.legend(handles=[Line2D([0], [0], marker="o", color="w", markerfacecolor=PALETTE[i], label=f"任务组{i+1}", markersize=8) for i in range(k)], frameon=False, loc="upper right")
    fig.suptitle(f"{tag} 服务区任务分区对比", x=.04, ha="left", fontsize=15, fontweight="bold", color=TEXT)
    save(fig, figdir / f"{tag}_plus01_任务分区地图对比.png")

    # 2. 资源需求—库存热力图。
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8))
    for ax, k in zip(axes, (2, 3)):
        d = res[k].copy(); resources = list(d["资源"].astype(str).drop_duplicates())
        groups = sorted(d["任务组"].unique()); mat = np.zeros((len(resources), len(groups)))
        inv = []
        for i, rr in enumerate(resources):
            row = d[d["资源"] == rr]
            inv.append(float(row["现有库存"].iloc[0]))
            for j, gg in enumerate(groups): mat[i, j] = float(row[row["任务组"] == gg]["需求数量"].iloc[0])
        im = ax.imshow(mat, aspect="auto", cmap="Blues", vmin=0)
        ax.set_yticks(range(len(resources))); ax.set_yticklabels(resources)
        ax.set_xticks(range(len(groups))); ax.set_xticklabels([f"组{int(g)}" for g in groups])
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]): ax.text(j, i, f"{mat[i,j]:.0f}/{inv[i]:.0f}", ha="center", va="center", fontsize=8, color=TEXT)
        ax.set_title(f"{k}组：需求/库存", fontweight="bold", color=TEXT); ax.set_xlabel("任务组"); ax.set_ylabel("资源")
        setup_ax(ax, None)
    fig.suptitle(f"{tag} 分区资源需求与现有库存", x=.04, ha="left", fontsize=15, fontweight="bold", color=TEXT)
    save(fig, figdir / f"{tag}_plus02_资源需求库存热力图.png")

    # 3. 工作量平衡：箱数、架次、作业时长的分面条形图。
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.2))
    metrics = [("箱数", "箱数"), ("架次", "架次"), ("作业时长_s", "作业时长 (h)")]
    for ax, (col, label) in zip(axes, metrics):
        names, vals, colors = [], [], []
        for k in (2, 3):
            for _, r in work[k].iterrows():
                names.append(f"{k}组-G{int(r['任务组'])}")
                vals.append(float(r[col]) / 3600 if col == "作业时长_s" else float(r[col]))
                colors.append(PALETTE[(int(r["任务组"]) - 1) % len(PALETTE)])
        ax.bar(names, vals, color=colors, alpha=.88)
        ax.set_title(label, fontweight="bold", color=TEXT); ax.tick_params(axis="x", rotation=35); setup_ax(ax, "y")
    fig.suptitle(f"{tag} 任务组工作量构成", x=.04, ha="left", fontsize=15, fontweight="bold", color=TEXT)
    save(fig, figdir / f"{tag}_plus03_任务组工作量分面.png")

    # 4. 关键评价指标比较。
    cols = [("资源缺口", "缺口"), ("总资源需求", "总需求"), ("通信风险均衡系数", "通信风险均衡"), ("工作量均衡系数", "工作量均衡")]
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.8))
    for ax, (col, label) in zip(axes, cols):
        bars = ax.bar(cmp["任务组数"].astype(str) + "组", cmp[col], color=[BLUE, ORANGE], width=.55)
        ax.set_title(label, fontweight="bold", color=TEXT); setup_ax(ax, "y")
        for b, v in zip(bars, cmp[col]): ax.text(b.get_x()+b.get_width()/2, b.get_height() + (max(cmp[col].max(), 1)*.03), f"{v:.2f}" if isinstance(v, float) else f"{v}", ha="center", fontsize=8)
    fig.suptitle(f"{tag} 2组/3组分区综合指标", x=.04, ha="left", fontsize=15, fontweight="bold", color=TEXT)
    save(fig, figdir / f"{tag}_plus04_综合指标比较.png")

    # 5. 缺口与冗余堆叠条形图。
    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = np.arange(len(cmp)); gap = cmp["资源缺口"].astype(float); red = cmp["资源冗余"].astype(float)
    ax.bar(x, gap, color=RED, label="资源缺口"); ax.bar(x, red, bottom=gap, color=TEAL, label="组内冗余")
    ax.set_xticks(x, [f"{int(k)}组" for k in cmp["任务组数"]]); ax.set_ylabel("资源数量")
    ax.set_title(f"{tag} 资源缺口与冗余", loc="left", fontweight="bold", color=TEXT); setup_ax(ax, "y"); ax.legend(frameon=False)
    save(fig, figdir / f"{tag}_plus05_资源缺口冗余.png")

    # 6. p4-4 局部搜索收敛曲线（p4-3没有搜索历史时跳过）。
    hist_path = out / f"{tag}_search_history.csv"
    if hist_path.exists():
        hist = pd.read_csv(hist_path, encoding="utf-8-sig")
        fig, ax = plt.subplots(figsize=(10, 5.4))
        if "迭代" in hist.columns:
            for k, g in hist.groupby("任务组数"):
                col = "目标值" if "目标值" in g.columns else g.columns[-1]
                ax.plot(g["迭代"], g[col], lw=1.7, color=PALETTE[int(k)-2], label=f"{int(k)}组")
        ax.set_xlabel("局部搜索迭代次数"); ax.set_ylabel("目标函数值")
        ax.set_title(f"{tag} 分区局部搜索收敛过程", loc="left", fontweight="bold", color=TEXT); setup_ax(ax, "both"); ax.legend(frameon=False)
        save(fig, figdir / f"{tag}_plus06_搜索收敛曲线.png")


def main():
    for tag in ("p3-3pro", "p3-4pro"):
        p3_visuals(tag)
    for tag in ("p4-3pro", "p4-4pro"):
        p4_visuals(tag, "p3-3pro" if tag == "p4-3pro" else "p3-4pro")
    print("增强可视化已生成：p3-3pro、p3-4pro、p4-3pro、p4-4pro 的 figures_plus 文件夹")


if __name__ == "__main__":
    main()
