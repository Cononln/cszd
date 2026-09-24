# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题背景数据可视化（q00）

说明：
本脚本只对附件给出的原始数据（调度中心/服务区、物资需求、逐箱货箱清单、
运输无人机、中继无人机、通信链路参数、镇龙乡地理空间数据）进行可视化呈现，
不涉及货箱组批、路径规划、资源调度等问题求解。
其中"机型载荷-航程包络"与"两阶段充电曲线""链路预算对比"三张图是把附录2、
附录3给出的计算公式直接代入附件参数画出来的参数关系图解，同样不包含任何
优化或决策变量，仅用于直观展示已知条件。

运行方式：
    python q00.py
输出：
    ./figures/ 目录下的一组 PNG 图片
"""

import os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.lines import Line2D
import rasterio

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "raw" / "tabular" / "无人机应急物资运输基础数据"
GEO_DIR = REPO_ROOT / "data" / "raw" / "geo" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据"
FIG_DIR = os.path.join(BASE_DIR, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

F_NODES = os.path.join(DATA_DIR, "调度中心与服务区.xlsx")
F_DEMAND = os.path.join(DATA_DIR, "物资需求与配送时限.xlsx")
F_TRANS = os.path.join(DATA_DIR, "运输无人机数据.xlsx")
F_RELAY = os.path.join(DATA_DIR, "中继无人机数据.xlsx")
F_COMM = os.path.join(DATA_DIR, "通信链路参数.xlsx")

F_DEM_TIF = os.path.join(GEO_DIR, "数字高程模型数据（DEM）", "镇龙乡及周边30米DEM.tif")
F_VILLAGE = os.path.join(GEO_DIR, "村镇点位", "镇龙乡及周边村镇点位.csv")
F_WATERBODY = os.path.join(GEO_DIR, "水体（面）", "镇龙乡及周边水体.csv")
F_WATERWAY = os.path.join(GEO_DIR, "水系（线）", "镇龙乡及周边水系.csv")
F_ROAD = os.path.join(GEO_DIR, "道路", "镇龙乡及周边道路.csv")

# ---------------------------------------------------------------------------
# 全局绘图样式（配色遵循 dataviz 规范：分类色定序使用、单一顺序色表示量级、
# 弱化网格与坐标轴、图例常驻、避免双 y 轴）
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = ["Microsoft YaHei", "SimHei", "Microsoft JhengHei"]
_AVAILABLE = {f.name for f in fm.fontManager.ttflist}
plt.rcParams["font.sans-serif"] = [f for f in _FONT_CANDIDATES if f in _AVAILABLE] + ["sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["font.size"] = 11
plt.rcParams["figure.dpi"] = 120
plt.rcParams["savefig.dpi"] = 200

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ_BLUE_5 = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95"]

MAT_ORDER = ["医疗物资", "饮用水", "应急食品", "生活卫生用品"]
MAT_COLOR = dict(zip(MAT_ORDER, CAT[:4]))
DRONE_ORDER = ["A", "B", "C"]
DRONE_COLOR = dict(zip(DRONE_ORDER, CAT[:3]))
DRONE_LABEL = {
    "A": "A 中轻载标准测试多旋翼",
    "B": "B 中载标准测试多旋翼",
    "C": "C 重载标准测试多旋翼",
}


def style_ax(ax, grid_axis="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(BASELINE)
        ax.spines[s].set_linewidth(0.8)
    ax.set_facecolor(SURFACE)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.xaxis.label.set_color(INK)
    ax.yaxis.label.set_color(INK)


def savefig(fig, name):
    path = os.path.join(FIG_DIR, name)
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(f"[已保存] {name}")


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
def load_nodes():
    df = pd.read_excel(F_NODES, sheet_name="数据", header=None)
    o01 = dict(
        编号=df.iat[2, 0], 名称=df.iat[2, 1],
        经度=float(df.iat[2, 2]), 纬度=float(df.iat[2, 3]), 海拔=float(df.iat[2, 4]),
    )
    sa = df.iloc[6:21].reset_index(drop=True)
    services = pd.DataFrame({
        "服务区编号": sa[0].values,
        "服务区名称": sa[1].values,
        "经度": sa[2].astype(float).values,
        "纬度": sa[3].astype(float).values,
        "海拔": sa[4].astype(float).values,
        "需保障人口": sa[5].astype(float).values,
    })
    return o01, services


def load_demand_summary():
    df = pd.read_excel(F_DEMAND, sheet_name="数据")
    df.columns = ["服务区编号", "物资类型", "总需求箱数", "首批必须送达箱数",
                  "单箱质量", "单箱体积", "应急优先系数", "首批截止时间", "期望送达时间"]
    return df


def load_box_list():
    df = pd.read_excel(F_DEMAND, sheet_name="逐箱货箱清单")
    df.columns = ["货箱编号", "服务区编号", "物资类型", "单箱质量", "单箱体积",
                  "是否首批保障", "首批截止时间", "期望送达时间", "应急优先系数"]
    return df


def load_transport_drone():
    df = pd.read_excel(F_TRANS, sheet_name="数据", header=None)
    cols = ["机型编号", "机型名称", "含电池空载总质量", "最大载货质量", "可用装载体积",
            "计划巡航速度", "空载标准航程", "满载标准航程", "电池可用能量", "返航电量下限",
            "工位固定准备时间", "每箱装载时间", "接收点基础交接时间", "每箱增加交接时间",
            "最大爬升速度", "最大下降速度", "爬升能耗效率", "下降能耗效率"]
    spec = df.iloc[2:5].reset_index(drop=True)
    spec.columns = cols
    for c in cols[2:]:
        spec[c] = spec[c].astype(float)

    fleet = df.iloc[8:16, 0:3].reset_index(drop=True)
    fleet.columns = ["无人机编号", "机型编号", "初始位置"]

    battery = df.iloc[19:22, 0:3].reset_index(drop=True)
    battery.columns = ["机型编号", "共享电池组总数", "等效完全充电时间"]
    battery["共享电池组总数"] = battery["共享电池组总数"].astype(float)
    battery["等效完全充电时间"] = battery["等效完全充电时间"].astype(float)
    return spec, fleet, battery


def load_relay_drone():
    df = pd.read_excel(F_RELAY, sheet_name="数据", header=None)
    cols = ["机型编号", "机型名称", "含能源组件空载总质量", "中继通信模块质量", "计划起飞总质量",
            "计划巡航速度", "巡航功率", "能源组件可用能量", "返航电量下限", "工位固定准备时间",
            "建链时间", "架次周转时间", "最大爬升速度", "最大下降速度", "爬升能耗效率",
            "下降能耗效率", "悬停功率", "通信附加功率", "最大悬停离地高度"]
    spec = df.iloc[2:3].reset_index(drop=True)
    spec.columns = cols
    for c in cols[2:]:
        spec[c] = spec[c].astype(float)

    fleet = df.iloc[6:8, 0:3].reset_index(drop=True)
    fleet.columns = ["中继无人机编号", "机型编号", "初始位置"]

    stock = df.iloc[11:12, 0:3].reset_index(drop=True)
    stock.columns = ["机型编号", "共享能源组件总数", "等效完全充电时间"]
    stock["共享能源组件总数"] = stock["共享能源组件总数"].astype(float)
    stock["等效完全充电时间"] = stock["等效完全充电时间"].astype(float)
    return spec, fleet, stock


def load_comm_params():
    df = pd.read_excel(F_COMM, sheet_name="数据", header=None)
    rows = df.iloc[2:16, [0, 1, 3, 4]].reset_index(drop=True)
    rows.columns = ["参数类别", "参数名称", "符号", "参数值"]
    rows["参数值"] = rows["参数值"].astype(float)
    return rows


def load_dem():
    with rasterio.open(F_DEM_TIF) as src:
        arr = src.read(1)
        bounds = src.bounds
    return arr, (bounds.left, bounds.right, bounds.bottom, bounds.top)


def load_villages():
    df = pd.read_csv(F_VILLAGE, encoding="utf-8-sig")
    return df


def load_waterbody():
    df = pd.read_csv(F_WATERBODY, encoding="utf-8-sig")
    return df


def load_waterway():
    df = pd.read_csv(F_WATERWAY, encoding="utf-8-sig")
    return df


def load_road():
    df = pd.read_csv(F_ROAD, encoding="utf-8-sig")
    return df


# ---------------------------------------------------------------------------
# 简单平面近似距离（仅用于描述节点间水平直线距离，不涉及路径/绕障求解）
# ---------------------------------------------------------------------------
def planar_distance_km(lon1, lat1, lon2, lat2):
    lat_mean = np.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111320.0 * np.cos(lat_mean)
    dy = (lat2 - lat1) * 110540.0
    return np.sqrt(dx ** 2 + dy ** 2) / 1000.0


# ---------------------------------------------------------------------------
# 简易山体阴影（仅作地形底图美化，不用于任何遮挡/通信判定计算）
# ---------------------------------------------------------------------------
def hillshade(elev, azimuth=315.0, altitude=45.0):
    gy, gx = np.gradient(elev.astype(float))
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.radians(azimuth)
    alt = np.radians(altitude)
    shaded = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos((az - np.pi / 2.0) - aspect)
    return np.clip(shaded, 0, 1)


def terrain_cmap():
    base = plt.cm.terrain(np.linspace(0.28, 1.0, 256))
    return ListedColormap(base)


# ===========================================================================
# 图 1：镇龙乡及周边区域地理总览（DEM + 水系水体 + 道路 + 村镇 + 调度中心/服务区）
# ===========================================================================
def fig_terrain_overview(o01, services):
    elev, extent = load_dem()
    shade = hillshade(elev)

    cmap = terrain_cmap()
    vmin, vmax = np.nanpercentile(elev, 1), np.nanpercentile(elev, 99)
    norm = Normalize(vmin=vmin, vmax=vmax)
    rgba = cmap(norm(elev))
    rgb = rgba[:, :, :3] * (0.45 + 0.55 * shade[:, :, None])
    rgb = np.clip(rgb, 0, 1)

    fig, ax = plt.subplots(figsize=(11, 9.2))
    ax.imshow(rgb, extent=extent, origin="upper", interpolation="bilinear", zorder=0)

    # 水体（面）
    wb = load_waterbody()
    verts = []
    for _, g in wb.groupby(["水体要素编号", "多边形编号", "环编号"]):
        verts.append(np.column_stack([g["经度"].values, g["纬度"].values]))
    pc = PolyCollection(verts, facecolor="#5598e7", edgecolor="none", alpha=0.55, zorder=1)
    ax.add_collection(pc)

    # 水系（线）
    wy = load_waterway()
    type_lw = {"河流": 1.4, "溪流": 0.8, "排水沟": 0.6, "渠道": 0.6}
    for wtype, lw in type_lw.items():
        segs = [g[["经度", "纬度"]].values for _, g in wy[wy["水系类型"] == wtype].groupby("水系要素编号")]
        if segs:
            ax.add_collection(LineCollection(segs, colors="#184f95", linewidths=lw, alpha=0.65, zorder=2))

    # 道路（按等级分层）
    rd = load_road()
    major = {"高速公路", "高速公路匝道", "干线公路", "干线公路连接线", "公路服务区"}
    secondary = {"主要道路", "主要道路连接线", "次要道路", "次要道路连接线", "一般道路"}
    tiers = [
        (major, 1.3, 0.85, "主干/高速道路"),
        (secondary, 0.8, 0.7, "次要/一般道路"),
        (None, 0.4, 0.45, "其他道路（乡村/步道）"),
    ]
    used = set()
    handles_roads = []
    for types, lw, alpha, label in tiers:
        if types is None:
            sub = rd[~rd["道路类型"].isin(used)]
        else:
            sub = rd[rd["道路类型"].isin(types)]
            used |= types
        segs = [g[["经度", "纬度"]].values for _, g in sub.groupby("道路要素编号")]
        if segs:
            ax.add_collection(LineCollection(segs, colors=INK2, linewidths=lw, alpha=alpha, zorder=3))
            handles_roads.append(Line2D([0], [0], color=INK2, lw=lw, alpha=alpha, label=label))

    # 村镇点位
    vil = load_villages()
    town = vil[vil["类别"] == "乡镇"]
    village = vil[vil["类别"] == "村庄"]
    ax.scatter(village["经度"], village["纬度"], s=5, color=MUTED, alpha=0.55, zorder=4, linewidths=0)
    ax.scatter(town["经度"], town["纬度"], s=26, color="#ffffff", edgecolor=INK2, linewidths=0.8,
               marker="s", zorder=5)

    # 服务区（按需保障人口编码大小）—— 先画服务区，让 O01 星标与短标签叠在最上层
    pop = services["需保障人口"].values
    size = 50 + 230 * (pop - pop.min()) / (pop.max() - pop.min() + 1e-9)
    ax.scatter(services["经度"], services["纬度"], s=size, color=CAT[0], alpha=0.85,
               edgecolor="white", linewidths=1.0, zorder=6)
    # 手动微调少数与邻近点位过近的标签偏移，避免遮挡（中心镇区聚集区）
    label_offset = {"S010": (11, 4), "S013": (11, -4), "S009": (0, 11), "S012": (10, 6)}
    for _, r in services.iterrows():
        code = r["服务区编号"]
        if code in label_offset:
            dx, dy = label_offset[code]
            ax.annotate(code, (r["经度"], r["纬度"]), xytext=(dx, dy),
                        textcoords="offset points", ha="left", va="center",
                        fontsize=7.4, color=INK, fontweight="bold", zorder=9)
        else:
            ax.annotate(code, (r["经度"], r["纬度"]), xytext=(0, 0),
                        textcoords="offset points", ha="center", va="center",
                        fontsize=7.2, color="white", fontweight="bold", zorder=8)

    # 调度中心 O01（短标签置于星标正下方，避免与密集服务区簇重叠；全称见图注）
    ax.scatter([o01["经度"]], [o01["纬度"]], s=220, marker="*", color=CAT[7],
               edgecolor=INK, linewidths=1.0, zorder=10)
    ax.annotate("O01", (o01["经度"], o01["纬度"]), xytext=(0, -13),
                textcoords="offset points", ha="center", fontsize=9.5, color=INK,
                fontweight="bold", zorder=10)

    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("经度（°）")
    ax.set_ylabel("纬度（°）")
    ax.set_title(
        f"图1  镇龙乡及周边区域地理总览：30 m DEM 地形、水系水体、道路网与调度节点\n"
        f"（O01 = {o01['名称']}；镇区周边服务区分布密集处已做标签避让）",
        loc="left", fontsize=13, fontweight="bold", color=INK, pad=12)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=INK2, labelsize=9)

    legend_handles = handles_roads + [
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#5598e7", alpha=0.6,
               markersize=9, label="水体（水库/池塘/蓄水池等）"),
        Line2D([0], [0], color="#184f95", lw=1.4, alpha=0.7, label="水系（河流/溪流）"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="white", markeredgecolor=INK2,
               markersize=7, label="乡镇点位"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=MUTED, markersize=5, label="村庄点位"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor=CAT[7], markeredgecolor=INK,
               markersize=14, label="O01 临时调度中心"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=CAT[0], markersize=10,
               label="服务区 Si（大小∝需保障人口）"),
    ]
    ax.legend(handles=legend_handles, loc="lower left", fontsize=8.3, framealpha=0.92,
              facecolor=SURFACE, edgecolor=BASELINE, ncol=1)

    cax = fig.add_axes([0.905, 0.30, 0.018, 0.35])
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, cax=cax)
    cb.set_label("地面高程（m）", fontsize=9, color=INK)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=INK2, labelsize=8)

    savefig(fig, "01_区域地理总览图.png")


# ===========================================================================
# 图 2：服务区与调度中心空间关系（距离、高差、人口）
# ===========================================================================
def fig_service_distance(o01, services):
    df = services.copy()
    df["水平距离(km)"] = planar_distance_km(o01["经度"], o01["纬度"], df["经度"], df["纬度"])
    df["高程差(m)"] = df["海拔"] - o01["海拔"]
    df = df.sort_values("服务区编号")

    fig, ax = plt.subplots(figsize=(8.6, 6.4))
    pop = df["需保障人口"].values
    size = 80 + 520 * (pop - pop.min()) / (pop.max() - pop.min() + 1e-9)
    sc = ax.scatter(df["水平距离(km)"], df["高程差(m)"], s=size, c=df["海拔"], cmap="Blues",
                     edgecolor=INK2, linewidths=0.8, alpha=0.9, zorder=3)
    for _, r in df.iterrows():
        ax.annotate(r["服务区编号"], (r["水平距离(km)"], r["高程差(m)"]), xytext=(6, 5),
                    textcoords="offset points", fontsize=8.6, color=INK)
    ax.axhline(0, color=BASELINE, lw=1.0, zorder=1)
    style_ax(ax, grid_axis="both")
    ax.set_xlabel("到 O01 的水平直线距离（km）")
    ax.set_ylabel("与 O01 的地面高程差（m）")
    ax.set_title("图2  15 个服务区相对调度中心 O01 的空间分布\n（气泡大小 ∝ 需保障人口，颜色 ∝ 服务区地面海拔）",
                 loc="left", fontsize=12.5, fontweight="bold", color=INK)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("地面海拔（m）", fontsize=9.5, color=INK)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=INK2, labelsize=8.5)
    savefig(fig, "02_服务区与调度中心空间关系.png")


# ===========================================================================
# 图 3：各服务区物资需求结构（堆叠柱状图）
# ===========================================================================
def fig_demand_stacked(demand):
    piv = demand.pivot_table(index="服务区编号", columns="物资类型", values="总需求箱数",
                              aggfunc="sum", fill_value=0)
    piv = piv.reindex(columns=MAT_ORDER)
    piv = piv.loc[sorted(piv.index)]

    fig, ax = plt.subplots(figsize=(11, 5.6))
    bottom = np.zeros(len(piv))
    x = np.arange(len(piv))
    for mat in MAT_ORDER:
        vals = piv[mat].values
        ax.bar(x, vals, bottom=bottom, width=0.62, color=MAT_COLOR[mat], label=mat,
               edgecolor=SURFACE, linewidth=1.2, zorder=3)
        bottom += vals
    totals = piv.sum(axis=1).values
    for xi, t in zip(x, totals):
        ax.annotate(f"{int(t)}", (xi, t), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8.3, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(piv.index, fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("总需求箱数（箱）")
    ax.set_title("图3  各服务区物资需求结构（按物资类型堆叠，总计80箱）", loc="left",
                 fontsize=13, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=9.5, frameon=False)
    savefig(fig, "03_各服务区物资需求结构.png")


# ===========================================================================
# 图 4：各服务区配送时限对比（期望送达时间 + 首批截止时间标记）
# ===========================================================================
def fig_timeliness(demand):
    df = demand.copy()
    df["期望送达时间_h"] = df["期望送达时间"] / 3600.0
    df["首批截止时间_h"] = df["首批截止时间"] / 3600.0
    order = sorted(df["服务区编号"].unique())

    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    n_mat = len(MAT_ORDER)
    width = 0.19
    x = np.arange(len(order))
    for i, mat in enumerate(MAT_ORDER):
        sub = df[df["物资类型"] == mat].set_index("服务区编号").reindex(order)
        offs = x + (i - (n_mat - 1) / 2) * width
        ax.bar(offs, sub["期望送达时间_h"], width=width * 0.92, color=MAT_COLOR[mat],
               label=mat, zorder=3)
        has_first = sub["首批截止时间_h"].notna()
        if has_first.any():
            ax.scatter(offs[has_first.values], sub.loc[has_first, "首批截止时间_h"],
                       marker="_", s=260, linewidths=2.4, color=INK, zorder=5)

    ax.scatter([], [], marker="_", s=260, linewidths=2.4, color=INK, label="首批截止时间（有首批要求的物资）")
    ax.set_xticks(x)
    ax.set_xticklabels(order, fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("时间（小时）")
    ax.set_title("图4  各服务区、各物资类型的期望送达时间与首批截止时间对比", loc="left",
                 fontsize=13, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=8.6, frameon=False, ncol=2)
    savefig(fig, "04_各服务区配送时限对比.png")


# ===========================================================================
# 图 5：应急优先系数热力图（服务区 × 物资类型）
# ===========================================================================
def fig_priority_heatmap(demand):
    piv = demand.pivot_table(index="服务区编号", columns="物资类型", values="应急优先系数", aggfunc="mean")
    piv = piv.reindex(columns=MAT_ORDER)
    piv = piv.loc[sorted(piv.index)]

    fig, ax = plt.subplots(figsize=(6.6, 8.4))
    cmap = ListedColormap(SEQ_BLUE_5[::-1] + ["#0d366b"]) if False else "Blues"
    im = ax.imshow(piv.values, cmap=cmap, aspect="auto", vmin=0, vmax=piv.values[~np.isnan(piv.values)].max())
    ax.set_xticks(range(len(MAT_ORDER)))
    ax.set_xticklabels(MAT_ORDER, fontsize=9.5, rotation=15, ha="right")
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(piv.index, fontsize=9.5)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if not np.isnan(v):
                txt_color = "white" if v > piv.values[~np.isnan(piv.values)].max() * 0.6 else INK
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8.6, color=txt_color)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0, colors=INK2)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.set_label("应急优先系数", fontsize=9.5, color=INK)
    cb.outline.set_visible(False)
    ax.set_title("图5  各服务区×物资类型的应急优先系数\n（空白表示该服务区无该类物资需求）", loc="left", fontsize=12.5,
                 fontweight="bold", color=INK, pad=10)
    savefig(fig, "05_应急优先系数热力图.png")


# ===========================================================================
# 图 6：逐箱货箱清单特征（质量/体积分布 + 首批保障占比）
# ===========================================================================
def fig_box_features(boxes):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))

    # 同一物资类型的单箱质量/体积在数据中恒为常数（无箱内差异），故用条形图
    # 直接展示各类物资的单箱规格，而非箱线图（否则四分位数退化为一条线）。
    box_n = boxes.groupby("物资类型").size().reindex(MAT_ORDER)

    ax = axes[0]
    mass = boxes.groupby("物资类型")["单箱质量"].first().reindex(MAT_ORDER)
    x = np.arange(len(MAT_ORDER))
    bars = ax.bar(x, mass.values, width=0.55, color=[MAT_COLOR[m] for m in MAT_ORDER], zorder=3)
    for b, v, n in zip(bars, mass.values, box_n.values):
        ax.annotate(f"{v:g} kg\n(n={n})", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8.6, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(MAT_ORDER, rotation=20, ha="right", fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("单箱质量（kg）")
    ax.set_title("(a) 各类物资单箱质量", fontsize=11.5, color=INK, loc="left")

    ax = axes[1]
    vol = boxes.groupby("物资类型")["单箱体积"].first().reindex(MAT_ORDER)
    bars = ax.bar(x, vol.values, width=0.55, color=[MAT_COLOR[m] for m in MAT_ORDER], zorder=3)
    for b, v, n in zip(bars, vol.values, box_n.values):
        ax.annotate(f"{v:g} m³\n(n={n})", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8.6, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(MAT_ORDER, rotation=20, ha="right", fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("单箱体积（m³）")
    ax.set_title("(b) 各类物资单箱体积", fontsize=11.5, color=INK, loc="left")

    ax = axes[2]
    cnt = boxes.groupby(["物资类型", "是否首批保障"]).size().unstack(fill_value=0)
    cnt = cnt.reindex(MAT_ORDER)
    x = np.arange(len(MAT_ORDER))
    yes = cnt.get("是", pd.Series(0, index=MAT_ORDER)).values
    no = cnt.get("否", pd.Series(0, index=MAT_ORDER)).values
    ax.bar(x, yes, width=0.55, color=CAT[7], label="首批保障箱", zorder=3)
    ax.bar(x, no, bottom=yes, width=0.55, color=BASELINE, label="非首批保障箱", zorder=3)
    for xi, y1, y2 in zip(x, yes, no):
        ax.annotate(f"{y1}/{y1+y2}", (xi, y1 + y2), xytext=(0, 3), textcoords="offset points",
                    ha="center", fontsize=8.3, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(MAT_ORDER, rotation=20, ha="right", fontsize=9)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("货箱数量（箱）")
    ax.set_title("(c) 首批保障箱占比（共80箱）", fontsize=11.5, color=INK, loc="left")
    ax.legend(loc="upper right", fontsize=8.6, frameon=False)

    fig.suptitle("图6  80个逐箱货箱清单的质量、体积与首批保障特征", fontsize=13.5,
                  fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    savefig(fig, "06_逐箱货箱特征分布.png")


# ===========================================================================
# 图 7：三种运输无人机机型参数对比
# ===========================================================================
def fig_drone_specs(spec):
    metrics = [
        ("最大载货质量", "kg"),
        ("可用装载体积", "m³"),
        ("电池可用能量", "kWh"),
        ("计划巡航速度", "m/s"),
        ("空载标准航程", "km", 1 / 1000),
        ("满载标准航程", "km", 1 / 1000),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(13, 8.2))
    for ax, m in zip(axes.flat, metrics):
        name, unit = m[0], m[1]
        scale = m[2] if len(m) > 2 else 1
        vals = spec.set_index("机型编号")[name].reindex(DRONE_ORDER).values * scale
        bars = ax.bar(DRONE_ORDER, vals, width=0.55,
                       color=[DRONE_COLOR[d] for d in DRONE_ORDER], zorder=3)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=9, color=INK2)
        style_ax(ax, grid_axis="y")
        ax.set_title(f"{name}（{unit}）", fontsize=11, color=INK, loc="left")
        ax.set_xticks(range(len(DRONE_ORDER)))
        ax.set_xticklabels(DRONE_ORDER, fontsize=10)
    handles = [Line2D([0], [0], marker="s", color="none", markerfacecolor=DRONE_COLOR[d],
                       markersize=11, label=DRONE_LABEL[d]) for d in DRONE_ORDER]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=9.6, frameon=False,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("图7  三种运输无人机机型（A/B/C）关键参数对比", fontsize=14,
                  fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    savefig(fig, "07_运输无人机机型参数对比.png")


# ===========================================================================
# 图 8：机型载荷-航程包络（依据附录2公式 L_g(q) 与附件参数绘制，非求解结果）
# ===========================================================================
def fig_range_envelope(spec):
    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    for d in DRONE_ORDER:
        row = spec[spec["机型编号"] == d].iloc[0]
        Qg, L0, LF = row["最大载货质量"], row["空载标准航程"], row["满载标准航程"]
        q = np.linspace(0, Qg, 200)
        Lq = L0 - (L0 - LF) * (q / Qg) ** 1.5
        ax.plot(q, Lq / 1000.0, color=DRONE_COLOR[d], lw=2.2, label=DRONE_LABEL[d], zorder=3)
        ax.scatter([0, Qg], [L0 / 1000.0, LF / 1000.0], color=DRONE_COLOR[d], s=32, zorder=4)
    style_ax(ax, grid_axis="both")
    ax.set_xlabel("有效载荷 q（kg）")
    ax.set_ylabel("等效航程 $L_g(q)$（km）")
    ax.set_title("图8  三种机型的载荷-等效航程包络曲线\n"
                 "（按附录2公式 $L_g(q)=L_g^0-(L_g^0-L_g^F)(q/Q_g)^{3/2}$ 与附件参数直接绘制，非求解结果）",
                 loc="left", fontsize=12, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=9.6, frameon=False)
    savefig(fig, "08_机型载荷-航程包络.png")


# ===========================================================================
# 图 9：共享能源资源库存与充电时间
# ===========================================================================
def fig_energy_stock(battery, relay_stock):
    stock = pd.concat([
        battery.rename(columns={"共享电池组总数": "数量", "等效完全充电时间": "充电时间"}),
        relay_stock.rename(columns={"共享能源组件总数": "数量", "等效完全充电时间": "充电时间"}),
    ], ignore_index=True)
    order = ["A", "B", "C", "R"]
    stock = stock.set_index("机型编号").reindex(order).reset_index()
    colors = [DRONE_COLOR.get(k, CAT[3]) for k in order]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    ax = axes[0]
    bars = ax.bar(stock["机型编号"], stock["数量"], width=0.55, color=colors, zorder=3)
    for b, v in zip(bars, stock["数量"]):
        ax.annotate(f"{int(v)}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=10, color=INK2)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("共享能源资源数量（组）")
    ax.set_title("(a) 各机型共享电池/能源组件总数", fontsize=11.5, color=INK, loc="left")

    ax = axes[1]
    bars = ax.bar(stock["机型编号"], stock["充电时间"] / 60.0, width=0.55, color=colors, zorder=3)
    for b, v in zip(bars, stock["充电时间"] / 60.0):
        ax.annotate(f"{v:.0f} min", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=10, color=INK2)
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("等效完全充电时间（分钟）")
    ax.set_title("(b) 各机型等效完全充电时间", fontsize=11.5, color=INK, loc="left")

    fig.suptitle("图9  运输无人机共享电池（A/B/C）与中继无人机能源组件（R）库存概览",
                  fontsize=13.5, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    savefig(fig, "09_共享能源资源库存与充电时间.png")


# ===========================================================================
# 图 10：两阶段充电曲线（依据附录2公式 t_chg(s) 绘制，非求解结果）
# ===========================================================================
def fig_charging_curve(battery, relay_stock):
    def t_chg(s, T_full):
        s = np.asarray(s, dtype=float)
        out = np.where(
            s < 0.90,
            T_full * (0.65 * (0.90 - s) / 0.90 + 0.35),
            T_full * 0.35 * (1 - s) / 0.10,
        )
        return out

    fig, ax = plt.subplots(figsize=(8.4, 6.2))
    s = np.linspace(0, 1, 400)
    combo = pd.concat([
        battery[["机型编号", "等效完全充电时间"]],
        relay_stock[["机型编号", "等效完全充电时间"]],
    ], ignore_index=True)
    for _, row in combo.iterrows():
        d = row["机型编号"]
        is_transport = d in DRONE_COLOR
        y = t_chg(s, row["等效完全充电时间"]) / 60.0
        # A型与R型的 T_full 恰好相同（均为1800s），曲线完全重合；用虚线区分中继侧，避免互相遮挡。
        ax.plot(s * 100, y, color=DRONE_COLOR.get(d, CAT[3]), lw=2.2,
                ls="-" if is_transport else "--",
                label=f"{d} 型（$T_{{full}}$={row['等效完全充电时间']:.0f}s）", zorder=3)
    ax.axvline(90, color=BASELINE, lw=1.0, ls="--", zorder=1)
    ax.annotate("SOC=90%\n（快充/慢充分界）", (90, ax.get_ylim()[1] * 0.12), xytext=(-8, 0),
                textcoords="offset points", ha="right", fontsize=8.6, color=INK2)
    style_ax(ax, grid_axis="both")
    ax.set_xlabel("任务结束时 SOC（%）")
    ax.set_ylabel("充至100%所需时间（分钟）")
    ax.set_title("图10  各类能源资源的两阶段充电时间曲线\n"
                 "（按附录2充电时间函数 $t_{chg}(s)$ 与附件 $T_{full}$ 直接绘制，非求解结果）",
                 loc="left", fontsize=12, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    savefig(fig, "10_两阶段充电曲线.png")


# ===========================================================================
# 图 11：中继无人机参数一览
# ===========================================================================
def fig_relay_specs(relay_spec):
    row = relay_spec.iloc[0]
    items = [
        ("巡航功率", row["巡航功率"], "kW"),
        ("悬停功率", row["悬停功率"], "kW"),
        ("通信附加功率", row["通信附加功率"], "kW"),
        ("能源组件可用能量", row["能源组件可用能量"], "kWh"),
        ("计划起飞总质量", row["计划起飞总质量"], "kg"),
        ("最大悬停离地高度", row["最大悬停离地高度"], "m"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1.3, 1]})

    ax = axes[0]
    names = [f"{n}\n（{u}）" for n, v, u in items]
    vals = [v for n, v, u in items]
    bars = ax.barh(names, vals, color=CAT[6], height=0.55, zorder=3)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:g}", (v, b.get_y() + b.get_height() / 2), xytext=(5, 0),
                    textcoords="offset points", va="center", fontsize=9.5, color=INK2)
    style_ax(ax, grid_axis="x")
    ax.set_title("(a) 中继无人机（R型）关键性能参数", fontsize=11.5, color=INK, loc="left")
    ax.invert_yaxis()

    ax = axes[1]
    time_items = [
        ("工位固定准备时间", row["工位固定准备时间"]),
        ("建链时间", row["建链时间"]),
        ("架次周转时间", row["架次周转时间"]),
    ]
    names2 = [n for n, v in time_items]
    vals2 = [v for n, v in time_items]
    bars2 = ax.bar(names2, vals2, color=CAT[3], width=0.5, zorder=3)
    for b, v in zip(bars2, vals2):
        ax.annotate(f"{v:g}s", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9.5, color=INK2)
    ax.set_xticks(range(len(names2)))
    ax.set_xticklabels(names2, fontsize=9, rotation=12, ha="right")
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("时间（s）")
    ax.set_title("(b) 中继无人机时间节点参数", fontsize=11.5, color=INK, loc="left")

    fig.suptitle("图11  中继无人机（R型，R01/R02 均驻留于 O01）参数一览", fontsize=13.5,
                  fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    savefig(fig, "11_中继无人机参数一览.png")


# ===========================================================================
# 图 12：通信链路发射/接收端参数对比
# ===========================================================================
def fig_comm_endpoints(comm):
    roles = ["运输无人机", "中继接入端", "中继回传端", "固定网关 G01"]
    role_map = {"运输无人机": "运输无人机", "中继接入端": "中继接入端",
                "中继回传端": "中继回传端", "固定网关 G01": "固定网关 G01"}
    pt = {}
    g = {}
    for r in roles:
        sub = comm[comm["参数类别"] == r]
        pt[r] = sub.loc[sub["参数名称"].str.contains("发射功率"), "参数值"].values[0]
        g[r] = sub.loc[sub["参数名称"].str.contains("天线增益"), "参数值"].values[0]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
    colors = CAT[:4]

    ax = axes[0]
    vals = [pt[r] for r in roles]
    bars = ax.bar(range(len(roles)), vals, color=colors, width=0.55, zorder=3)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:g}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9.5, color=INK2)
    ax.set_xticks(range(len(roles)))
    ax.set_xticklabels(roles, fontsize=9, rotation=15, ha="right")
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("发射功率（dBm）")
    ax.set_title("(a) 各通信端点发射功率", fontsize=11.5, color=INK, loc="left")

    ax = axes[1]
    vals = [g[r] for r in roles]
    bars = ax.bar(range(len(roles)), vals, color=colors, width=0.55, zorder=3)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:g}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=9.5, color=INK2)
    ax.set_xticks(range(len(roles)))
    ax.set_xticklabels(roles, fontsize=9, rotation=15, ha="right")
    style_ax(ax, grid_axis="y")
    ax.set_ylabel("天线增益（dBi）")
    ax.set_title("(b) 各通信端点天线增益", fontsize=11.5, color=INK, loc="left")

    fig.suptitle("图12  通信端点（运输无人机 / 中继接入端 / 中继回传端 / 固定网关G01）发射与增益参数",
                  fontsize=13, fontweight="bold", color=INK, x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    savefig(fig, "12_通信链路发射接收参数对比.png")


# ===========================================================================
# 图 13：链路预算对比（依据附录3公式直接代入附件参数计算，非通信状态求解）
# ===========================================================================
def fig_link_budget(comm):
    Lsys = comm.loc[comm["参数名称"].str.contains("系统损耗"), "参数值"].values[0]
    Lobs = comm.loc[comm["参数名称"].str.contains("地形遮挡"), "参数值"].values[0]
    Psens = comm.loc[comm["参数名称"].str.contains("接收灵敏度"), "参数值"].values[0]
    M = comm.loc[comm["参数名称"].str.contains("衰落裕量"), "参数值"].values[0]
    Pth = Psens + M

    def role(name):
        sub = comm[comm["参数类别"] == name]
        pt = sub.loc[sub["参数名称"].str.contains("发射功率"), "参数值"].values[0]
        g = sub.loc[sub["参数名称"].str.contains("天线增益"), "参数值"].values[0]
        return pt, g

    uav_pt, uav_g = role("运输无人机")
    acc_pt, acc_g = role("中继接入端")
    bh_pt, bh_g = role("中继回传端")
    gw_pt, gw_g = role("固定网关 G01")

    def lmax(pt_a, g_a, g_b):
        return pt_a + g_a + g_b - Lsys - Pth

    links = {
        "运输无人机－G01\n（直连）": min(lmax(uav_pt, uav_g, gw_g), lmax(gw_pt, gw_g, uav_g)),
        "运输无人机－中继接入端\n（接入链路）": min(lmax(uav_pt, uav_g, acc_g), lmax(acc_pt, acc_g, uav_g)),
        "中继回传端－G01\n（回传链路）": min(lmax(bh_pt, bh_g, gw_g), lmax(gw_pt, gw_g, bh_g)),
    }

    fig, ax = plt.subplots(figsize=(8.6, 5.8))
    names = list(links.keys())
    vals = list(links.values())
    bars = ax.barh(names, vals, color=CAT[:3], height=0.5, zorder=3)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.1f} dB", (v, b.get_y() + b.get_height() / 2), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=10, color=INK2)
    ax.axvline(Lobs, color=INK, lw=1.2, ls="--", zorder=1)
    ax.annotate(f"地形遮挡附加损耗 $L_{{obs}}$={Lobs:g} dB", (Lobs, 0), xycoords=("data", "axes fraction"),
                xytext=(6, 8), textcoords="offset points", fontsize=8.6, color=INK2)
    style_ax(ax, grid_axis="x")
    ax.invert_yaxis()
    ax.set_xlabel(r"双向链路最大允许总传播损耗 $L_{max}^{a\leftrightarrow b}$（dB）")
    ax.set_title("图13  三类通信链路的最大允许传播损耗对比\n"
                 "（按附录3公式 $L_{max}=P_t+G_t+G_r-L_{sys}-P_{th}$ 与附件参数计算，非通信状态求解结果）",
                 loc="left", fontsize=11.8, fontweight="bold", color=INK)
    savefig(fig, "13_链路预算对比.png")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    print("正在读取附件数据 ...")
    o01, services = load_nodes()
    demand = load_demand_summary()
    boxes = load_box_list()
    trans_spec, trans_fleet, trans_battery = load_transport_drone()
    relay_spec, relay_fleet, relay_stock = load_relay_drone()
    comm = load_comm_params()

    print("正在绘制图表 ...")
    fig_terrain_overview(o01, services)
    fig_service_distance(o01, services)
    fig_demand_stacked(demand)
    fig_timeliness(demand)
    fig_priority_heatmap(demand)
    fig_box_features(boxes)
    fig_drone_specs(trans_spec)
    fig_range_envelope(trans_spec)
    fig_energy_stock(trans_battery, relay_stock)
    fig_charging_curve(trans_battery, relay_stock)
    fig_relay_specs(relay_spec)
    fig_comm_endpoints(comm)
    fig_link_budget(comm)

    print(f"\n全部图表已输出至：{FIG_DIR}")


if __name__ == "__main__":
    main()
