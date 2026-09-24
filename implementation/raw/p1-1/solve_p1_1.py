# -*- coding: utf-8 -*-
"""
问题一（P1-1）独立求解程序

本文件是一个全新的、独立的求解入口，不读取或改写项目根目录中已有的
q1_1.py、q1_21.py、q1_22.py、q1_23.py及其结果文件。

完成内容：
  1. 单点往返最大安全载荷和可行货箱组批；
  2. 架次数、总能耗、累计作业时间的多目标组批优化；
  3. 返航安全余量敏感性分析；
  4. 输出结果表、说明文件和多种图形。

运行：
  python solve_p1_1.py

输出全部写入本文件所在目录下的 outputs/ 和 figures/，不会覆盖项目根目录
已有的任何结果。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from scipy.optimize import brentq, milp, LinearConstraint, Bounds
from scipy.sparse import csr_matrix


ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parents[1]
DATA = REPO_ROOT / "data" / "raw" / "tabular" / "无人机应急物资运输基础数据"
GEO = REPO_ROOT / "data" / "raw" / "geo" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据"
OUT = Path(__file__).resolve().parent / "outputs"
FIG = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

G = 9.8
J_PER_KWH = 3.6e6
CLEARANCE_M = 50.0
SERVICE_HEIGHT_M = 30.0
EPS = 1e-8


def fpath(name: str) -> Path:
    return DATA / name


def first_tif() -> Path:
    files = list(GEO.rglob("*.tif"))
    if not files:
        raise FileNotFoundError(f"未找到DEM tif文件：{GEO}")
    return files[0]


def numeric(x, default=np.nan) -> float:
    try:
        if pd.isna(x) or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def read_inputs() -> Tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """读取调度中心、服务区、逐箱货箱和运输机型参数。"""
    node_raw = pd.read_excel(fpath("调度中心与服务区.xlsx"), sheet_name=0, header=None)
    # 工作表前两行为标题和字段名，第3行为O01数据。
    o_row = node_raw.iloc[2]
    center = {
        "编号": str(o_row.iloc[0]), "经度": float(o_row.iloc[2]),
        "纬度": float(o_row.iloc[3]), "海拔": float(o_row.iloc[4])
    }
    service_raw = node_raw.iloc[6:].copy()
    service_raw = service_raw[service_raw.iloc[:, 0].astype(str).str.startswith("S")]
    services = pd.DataFrame({
        "服务区编号": service_raw.iloc[:, 0].astype(str),
        "服务区名称": service_raw.iloc[:, 1].astype(str),
        "经度": pd.to_numeric(service_raw.iloc[:, 2]),
        "纬度": pd.to_numeric(service_raw.iloc[:, 3]),
        "海拔": pd.to_numeric(service_raw.iloc[:, 4]),
    }).reset_index(drop=True)

    demand_file = fpath("物资需求与配送时限.xlsx")
    boxes = pd.read_excel(demand_file, sheet_name=1, header=0).copy()
    boxes = boxes[boxes.iloc[:, 0].astype(str).str.startswith("S")].copy()
    boxes.columns = ["货箱编号", "服务区编号", "物资类型", "单箱质量_kg", "单箱体积_m3",
                     "是否首批保障", "首批截止时间_s", "期望送达时间_s", "应急优先系数"]
    for col in ["单箱质量_kg", "单箱体积_m3", "首批截止时间_s", "期望送达时间_s", "应急优先系数"]:
        boxes[col] = pd.to_numeric(boxes[col], errors="coerce")
    boxes["是否首批保障"] = boxes["是否首批保障"].astype(str).eq("是")
    boxes = boxes.reset_index(drop=True)

    trans_raw = pd.read_excel(fpath("运输无人机数据.xlsx"), sheet_name=0, header=0)
    # 同一工作表下方还包含共享电池库存，必须通过“空载质量”列为数值
    # 筛掉库存行，避免把电池库存误读成无人机机型。
    trans_raw = trans_raw[
        trans_raw.iloc[:, 0].astype(str).isin(["A", "B", "C"]) &
        pd.to_numeric(trans_raw.iloc[:, 2], errors="coerce").notna() &
        pd.to_numeric(trans_raw.iloc[:, 3], errors="coerce").notna()
    ].copy()
    trans_raw.columns = ["机型编号", "机型名称", "空载质量_kg", "最大载货质量_kg", "装载体积_m3",
                         "巡航速度_mps", "空载航程_m", "满载航程_m", "电池能量_kWh",
                         "返航电量下限_pct", "固定准备时间_s", "每箱装载时间_s", "基础交接时间_s",
                         "每箱交接时间_s", "爬升速度_mps", "下降速度_mps", "爬升效率", "下降效率"]
    for c in trans_raw.columns[2:]:
        trans_raw[c] = pd.to_numeric(trans_raw[c], errors="coerce")
    trans_raw = trans_raw.reset_index(drop=True)
    return center, services, boxes, trans_raw


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    """适用于本题小区域的球面距离。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def path_max_elevation(ds, lon1, lat1, lon2, lat2) -> float:
    d = haversine_m(lon1, lat1, lon2, lat2)
    n = max(30, int(math.ceil(d / 30.0)))
    lons = np.linspace(lon1, lon2, n)
    lats = np.linspace(lat1, lat2, n)
    inv = ~ds.transform
    cols, rows = inv * (lons, lats)
    cols = np.clip(np.rint(cols).astype(int), 0, ds.width - 1)
    rows = np.clip(np.rint(rows).astype(int), 0, ds.height - 1)
    z = ds.read(1)[rows, cols].astype(float)
    z = z[z != ds.nodata] if ds.nodata is not None else z
    if z.size == 0:
        raise ValueError("DEM路径采样全部为NoData")
    return float(np.nanmax(z))


def make_geometry(center: dict, services: pd.DataFrame) -> pd.DataFrame:
    records = []
    with rasterio.open(first_tif()) as ds:
        for _, s in services.iterrows():
            d = haversine_m(center["经度"], center["纬度"], s["经度"], s["纬度"])
            zmax = path_max_elevation(ds, center["经度"], center["纬度"], s["经度"], s["纬度"])
            cruise = zmax + CLEARANCE_M
            o_h = center["海拔"]
            s_h = float(s["海拔"]) + SERVICE_HEIGHT_M
            records.append({
                "服务区编号": s["服务区编号"], "水平距离_m": d,
                "路径最高地面高程_m": zmax, "巡航海拔_m": cruise,
                "去程爬升_m": max(0.0, cruise - o_h),
                "去程下降_m": max(0.0, cruise - s_h),
                "返程爬升_m": max(0.0, cruise - s_h),
                "返程下降_m": max(0.0, cruise - o_h),
            })
    return pd.DataFrame(records)


def loaded_range(q, row) -> float:
    q = min(max(float(q), 0.0), float(row["最大载货质量_kg"]))
    return float(row["空载航程_m"] - (row["空载航程_m"] - row["满载航程_m"]) *
                 (q / row["最大载货质量_kg"]) ** 1.5)


def horizontal_energy(d, q, row) -> float:
    return float(d / loaded_range(q, row) * row["电池能量_kWh"])


def climb_energy(h, q, row) -> float:
    return float((row["空载质量_kg"] + q) * G * max(h, 0.0) /
                 (J_PER_KWH * row["爬升效率"]))


def leg_time(h_up, h_down, d, row) -> float:
    return float(h_up / row["爬升速度_mps"] + d / row["巡航速度_mps"] +
                 h_down / row["下降速度_mps"])


def round_trip(q, geo, row) -> Tuple[float, float]:
    """返回（往返能耗kWh，飞行时间s），下降附加能耗按题设为0。"""
    d = geo["水平距离_m"]
    e_out = horizontal_energy(d, q, row) + climb_energy(geo["去程爬升_m"], q, row)
    e_back = horizontal_energy(d, 0.0, row) + climb_energy(geo["返程爬升_m"], 0.0, row)
    t = leg_time(geo["去程爬升_m"], geo["去程下降_m"], d, row)
    t += leg_time(geo["返程爬升_m"], geo["返程下降_m"], d, row)
    return e_out + e_back, t


def qmax_table(geometry: pd.DataFrame, specs: pd.DataFrame, rho: float) -> pd.DataFrame:
    out = []
    for _, dr in specs.iterrows():
        limit = (1.0 - rho) * dr["电池能量_kWh"]
        for _, geo in geometry.iterrows():
            q_cap = float(dr["最大载货质量_kg"])
            f0 = round_trip(0.0, geo, dr)[0] - limit
            f1 = round_trip(q_cap, geo, dr)[0] - limit
            if f0 > EPS:
                q = 0.0
                reason = "空载也超出能量上限"
            elif f1 <= EPS:
                q = q_cap
                reason = "质量上限"
            else:
                q = brentq(lambda x: round_trip(x, geo, dr)[0] - limit, 0.0, q_cap)
                reason = "返航安全能量上限"
            e, t = round_trip(q, geo, dr)
            out.append({"返航余量": rho, "机型编号": dr["机型编号"],
                        "服务区编号": geo["服务区编号"], "最大安全载荷_kg": q,
                        "质量上限_kg": q_cap, "能量上限_kWh": limit,
                        "qmax对应往返能耗_kWh": e, "往返飞行时间_s": t,
                        "限制因素": reason})
    return pd.DataFrame(out)


def batch_time(boxes: pd.DataFrame, service: str, machine: pd.Series, geo: pd.Series) -> float:
    n = len(boxes)
    flight = round_trip(float(boxes["单箱质量_kg"].sum()), geo, machine)[1]
    return float(machine["固定准备时间_s"] + n * machine["每箱装载时间_s"] + flight +
                 machine["基础交接时间_s"] + n * machine["每箱交接时间_s"])


def enumerate_candidates(boxes: pd.DataFrame, services: pd.DataFrame, specs: pd.DataFrame,
                         geometry: pd.DataFrame, qmax: pd.DataFrame) -> pd.DataFrame:
    """枚举每个服务区的可行货箱子集×机型候选。"""
    rows = []
    qlookup = {(r["机型编号"], r["服务区编号"]): r["最大安全载荷_kg"]
               for _, r in qmax.iterrows()}
    geomap = {r["服务区编号"]: r for _, r in geometry.iterrows()}
    for service, group in boxes.groupby("服务区编号", sort=True):
        group = group.sort_values(["是否首批保障", "应急优先系数", "单箱质量_kg"],
                                  ascending=[False, False, False]).reset_index(drop=True)
        recs = group.to_dict("records")
        max_mass = max(qlookup[(g, service)] for g in specs["机型编号"])
        max_vol = float(specs["装载体积_m3"].max())
        subsets: List[List[int]] = []

        def dfs(pos: int, chosen: List[int], mass: float, vol: float):
            if chosen:
                subsets.append(chosen.copy())
            for j in range(pos, len(recs)):
                m = mass + float(recs[j]["单箱质量_kg"])
                v = vol + float(recs[j]["单箱体积_m3"])
                if m > max_mass + EPS or v > max_vol + EPS:
                    continue
                chosen.append(j)
                dfs(j + 1, chosen, m, v)
                chosen.pop()

        dfs(0, [], 0.0, 0.0)
        for idxs in subsets:
            sub = group.iloc[idxs]
            mass = float(sub["单箱质量_kg"].sum())
            vol = float(sub["单箱体积_m3"].sum())
            for _, dr in specs.iterrows():
                g = dr["机型编号"]
                if mass > qlookup[(g, service)] + EPS or vol > dr["装载体积_m3"] + EPS:
                    continue
                geo = geomap[service]
                e, _ = round_trip(mass, geo, dr)
                t = batch_time(sub, service, dr, geo)
                rows.append({
                    "候选编号": len(rows), "服务区编号": service, "机型编号": g,
                    "货箱列表": "|".join(sub["货箱编号"].tolist()), "箱数": len(sub),
                    "总质量_kg": mass, "总体积_m3": vol, "往返能耗_kWh": e,
                    "累计作业时间_s": t, "质量上限_kg": qlookup[(g, service)],
                    "体积上限_m3": dr["装载体积_m3"],
                    "首批箱数": int(sub["是否首批保障"].sum()),
                    "优先级总分": float(sub["应急优先系数"].sum()),
                })
    cand = pd.DataFrame(rows)
    if cand.empty:
        raise RuntimeError("没有生成任何可行货箱组批候选，请检查数据或能耗公式")
    return cand


def solve_set_partition(cand: pd.DataFrame, boxes: pd.DataFrame, objective: str,
                        scales: Dict[str, float] | None = None) -> Tuple[pd.DataFrame, dict]:
    """对货箱执行覆盖的0-1集合划分。

    题目明确禁止跨服务区组批，因此全局模型可严格分解为15个相互独立的
    服务区集合划分。按服务区分别求解既保持全局最优性，又避免在一个大MILP
    中重复处理互不相连的变量。
    """
    selected_parts = []
    objective_value = 0.0
    messages = []
    for service, bsub in boxes.groupby("服务区编号", sort=True):
        csub = cand[cand["服务区编号"] == service].reset_index(drop=True)
        # 同一个货箱子集不需要同时保留三种机型：问题一不考虑实体机和
        # 电池资源耦合，因此对当前目标保留该子集的最优机型即可。
        if objective == "N":
            score = csub["往返能耗_kWh"] * 1e-6 + csub["累计作业时间_s"] * 1e-12
        elif objective == "E":
            score = csub["往返能耗_kWh"]
        elif objective == "T":
            score = csub["累计作业时间_s"]
        else:
            sc = scales or {"wN": 1/3, "wE": 1/3, "wT": 1/3, "N": 20.0, "E": 100.0, "T": 50000.0}
            score = (sc["wN"] / sc["N"] +
                     sc["wE"] * csub["往返能耗_kWh"] / sc["E"] +
                     sc["wT"] * csub["累计作业时间_s"] / sc["T"])
        csub = csub.assign(_score=score).sort_values("_score").drop_duplicates("货箱列表").drop(columns="_score").reset_index(drop=True)
        if len(csub) > 5000:
            local = greedy_partition(csub, bsub, objective, scales)
            selected_parts.append(local)
            if objective == "N":
                objective_value += len(local)
            elif objective == "E":
                objective_value += local["往返能耗_kWh"].sum()
            elif objective == "T":
                objective_value += local["累计作业时间_s"].sum()
            else:
                sc = scales or {"wN": 1/3, "wE": 1/3, "wT": 1/3, "N": 20.0, "E": 100.0, "T": 50000.0}
                objective_value += (sc["wN"] * len(local) / sc["N"] +
                                    sc["wE"] * local["往返能耗_kWh"].sum() / sc["E"] +
                                    sc["wT"] * local["累计作业时间_s"].sum() / sc["T"])
            messages.append(f"{service}: greedy large-column fallback")
            continue
        ids = bsub["货箱编号"].tolist()
        id_to_row = {x: i for i, x in enumerate(ids)}
        mat = np.zeros((len(ids), len(csub)), dtype=float)
        for j, s in enumerate(csub["货箱列表"]):
            for bid in s.split("|"):
                mat[id_to_row[bid], j] = 1.0
        if objective == "N":
            c = np.ones(len(csub))
        elif objective == "E":
            c = csub["往返能耗_kWh"].to_numpy(float)
        elif objective == "T":
            c = csub["累计作业时间_s"].to_numpy(float)
        elif objective == "weighted":
            sc = scales or {"N": 20.0, "E": 100.0, "T": 50000.0}
            c = (sc["wN"] / sc["N"] +
                 sc["wE"] * csub["往返能耗_kWh"].to_numpy(float) / sc["E"] +
                 sc["wT"] * csub["累计作业时间_s"].to_numpy(float) / sc["T"])
        else:
            raise ValueError(objective)
        res = milp(c=c, integrality=np.ones(len(csub)), bounds=Bounds(0, 1),
                   constraints=LinearConstraint(csr_matrix(mat), np.ones(len(ids)), np.ones(len(ids))),
                   options={"time_limit": 20.0, "mip_rel_gap": 1e-8})
        # HiGHS在时间上限到达时可能已经给出可行整数解，保留该解而不是
        # 让整个敏感性分析失败；随后仍会执行覆盖性复核。
        if not res.success and res.x is None:
            raise RuntimeError(f"服务区{service}集合划分求解失败：{res.message}")
        idx = np.flatnonzero(np.asarray(res.x) > 0.5)
        if len(idx) == 0:
            raise RuntimeError(f"服务区{service}未得到可行覆盖解：{res.message}")
        selected_parts.append(csub.iloc[idx])
        objective_value += float(res.fun)
        messages.append(f"{service}: {res.message}")
    sel = pd.concat(selected_parts, ignore_index=True)
    metrics = {"架次数": int(len(sel)), "总能耗_kWh": float(sel["往返能耗_kWh"].sum()),
               "累计作业时间_s": float(sel["累计作业时间_s"].sum()),
               "目标值": objective_value, "求解状态": "; ".join(messages)}
    return sel, metrics


def annotate_batches(sel: pd.DataFrame) -> pd.DataFrame:
    out = sel.copy()
    out.insert(0, "批次编号", [f"{r['服务区编号']}-B{i+1:02d}" for i, (_, r) in enumerate(out.iterrows())])
    return out


def greedy_partition(csub: pd.DataFrame, bsub: pd.DataFrame, objective: str,
                     scales: Dict[str, float] | None = None) -> pd.DataFrame:
    """大候选池的快速可行组批器。

    S001包含大量可行子集，直接把全部列交给MILP会让不同子集之间的对称
    分支非常慢。该启发式始终只选择“剩余货箱的可行子集”，所以不会破坏
    货箱唯一性和硬约束；小服务区仍使用精确集合划分。
    """
    remaining = set(bsub["货箱编号"])
    selected = []
    while remaining:
        feasible = []
        for _, r in csub.iterrows():
            ids = set(r["货箱列表"].split("|"))
            if ids and ids.issubset(remaining):
                n = len(ids)
                if objective == "N":
                    key = (-n, -float(r["优先级总分"]), float(r["往返能耗_kWh"]))
                elif objective == "E":
                    key = (float(r["往返能耗_kWh"]) / (n ** 0.8), -n, float(r["往返能耗_kWh"]))
                elif objective == "T":
                    key = (float(r["累计作业时间_s"]) / (n ** 0.8), -n, float(r["累计作业时间_s"]))
                else:
                    sc = scales or {"wN": 1/3, "wE": 1/3, "wT": 1/3, "N": 20.0, "E": 100.0, "T": 50000.0}
                    cost = sc["wN"] / sc["N"] + sc["wE"] * float(r["往返能耗_kWh"]) / sc["E"] + sc["wT"] * float(r["累计作业时间_s"]) / sc["T"]
                    key = (cost / (n ** 0.8), -n, float(r["往返能耗_kWh"]))
                feasible.append((key, r))
        if not feasible:
            raise RuntimeError(f"服务区{bsub['服务区编号'].iloc[0]}的启发式组批无法覆盖剩余货箱")
        feasible.sort(key=lambda z: z[0])
        r = feasible[0][1]
        selected.append(r)
        remaining -= set(r["货箱列表"].split("|"))
    return pd.DataFrame(selected).reset_index(drop=True)


def expand_assignment(sel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in sel.iterrows():
        for bid in r["货箱列表"].split("|"):
            rows.append({"货箱编号": bid, "服务区编号": r["服务区编号"],
                         "批次编号": r["批次编号"], "机型编号": r["机型编号"]})
    return pd.DataFrame(rows)


def metrics_from(sel: pd.DataFrame) -> dict:
    return {"架次数": int(len(sel)), "总能耗_kWh": float(sel["往返能耗_kWh"].sum()),
            "累计作业时间_s": float(sel["累计作业时间_s"].sum())}


def save_csv(df: pd.DataFrame, name: str):
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")


def configure_plot():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.dpi"] = 220


def savefig(fig, name: str):
    fig.savefig(FIG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def make_figures(qmax: pd.DataFrame, base_batches: pd.DataFrame, scen: pd.DataFrame,
                 tradeoffs: pd.DataFrame, services: pd.DataFrame):
    configure_plot()
    colors = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
    order = services["服务区编号"].tolist()

    # 1. 最大安全载荷
    fig, ax = plt.subplots(figsize=(13, 5.8))
    x = np.arange(len(order)); width = 0.25
    for k, g in enumerate(["A", "B", "C"]):
        sub = qmax[qmax["机型编号"] == g].set_index("服务区编号").reindex(order)
        ax.bar(x + (k - 1) * width, sub["最大安全载荷_kg"], width, label=f"机型{g}", color=colors[g])
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=45, ha="right")
    ax.set_ylabel("最大安全载荷（kg）"); ax.set_title("问题一：各机型—服务区单点往返最大安全载荷")
    ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); savefig(fig, "p1-1_01_最大安全载荷.png")

    # 2. 能量利用率热力图
    piv = qmax.pivot(index="服务区编号", columns="机型编号", values="qmax对应往返能耗_kWh") / \
          qmax.pivot(index="服务区编号", columns="机型编号", values="能量上限_kWh")
    piv = piv.reindex(index=order, columns=["A", "B", "C"])
    fig, ax = plt.subplots(figsize=(5.2, 7.6))
    im = ax.imshow(piv.values, cmap="YlOrRd", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(3)); ax.set_xticklabels(["A", "B", "C"])
    ax.set_yticks(range(len(order))); ax.set_yticklabels(order)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax.text(j, i, f"{piv.iloc[i,j]:.0%}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="qmax对应能耗 / 安全能量上限")
    ax.set_title("返航安全能量利用率热力图"); fig.tight_layout(); savefig(fig, "p1-1_02_能量利用率热力图.png")

    # 3. 基准组批结构
    count = base_batches.groupby(["服务区编号", "机型编号"]).size().unstack(fill_value=0).reindex(order, fill_value=0)
    fig, ax = plt.subplots(figsize=(12, 5.6))
    bottom = np.zeros(len(count))
    for g in ["A", "B", "C"]:
        vals = count[g].to_numpy() if g in count else np.zeros(len(count))
        ax.bar(order, vals, bottom=bottom, label=f"机型{g}", color=colors[g]); bottom += vals
    ax.set_ylabel("架次数"); ax.set_title("问题一第1小问：可行货箱组批中的机型与架次")
    ax.tick_params(axis="x", rotation=45); ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout()
    savefig(fig, "p1-1_03_基准组批架次构成.png")

    # 4. 多目标权衡散点
    fig, ax = plt.subplots(figsize=(7.8, 5.6))
    grouped = tradeoffs.assign(_e=tradeoffs["总能耗_kWh"].round(5), _t=tradeoffs["累计作业时间_h"].round(5)).groupby(["_e", "_t"], as_index=False).agg({"方案": "/".join, "总能耗_kWh": "first", "累计作业时间_h": "first"})
    for _, r in grouped.iterrows():
        ax.scatter(r["总能耗_kWh"], r["累计作业时间_h"], s=80)
        ax.annotate(r["方案"], (r["总能耗_kWh"], r["累计作业时间_h"]), xytext=(5, 5), textcoords="offset points", fontsize=8)
    ax.set_xlabel("总运输能耗（kWh）"); ax.set_ylabel("累计作业时间（h）")
    ax.set_title("问题一第2小问：架次—能耗—时间方案对比")
    ax.grid(alpha=.25); fig.tight_layout(); savefig(fig, "p1-1_04_多目标权衡.png")

    # 5. 返航余量敏感性
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for g in ["A", "B", "C"]:
        s = scen[scen["机型编号"] == g].groupby("返航余量")["平均最大安全载荷_kg"].mean()
        axes[0].plot(s.index * 100, s.values, marker="o", label=f"机型{g}")
    axes[0].set_xlabel("返航安全余量（%）"); axes[0].set_ylabel("跨服务区平均最大安全载荷（kg）")
    axes[0].grid(alpha=.25); axes[0].legend(); axes[0].set_title("安全余量对最大载荷的影响")
    s2 = scen.drop_duplicates(["返航余量", "平衡方案架次数"]).sort_values("返航余量")
    axes[1].plot(s2["返航余量"] * 100, s2["平衡方案架次数"], marker="o", color="#e34948")
    axes[1].set_xlabel("返航安全余量（%）"); axes[1].set_ylabel("平衡方案架次数")
    axes[1].grid(alpha=.25); axes[1].set_title("安全余量对组批架次数的影响")
    fig.tight_layout(); savefig(fig, "p1-1_05_返航余量敏感性.png")


def main():
    center, services, boxes, specs = read_inputs()
    geometry = make_geometry(center, services)
    geometry.to_csv(OUT / "p1-1_航段几何参数.csv", index=False, encoding="utf-8-sig")

    base_rho = float(specs["返航电量下限_pct"].iloc[0]) / 100.0
    qmax = qmax_table(geometry, specs, base_rho)
    save_csv(qmax, "p1-1_最大安全载荷.csv")

    # 第1小问：以最少架次为主目标，得到满足全部硬约束的基准组批。
    cand = enumerate_candidates(boxes, services, specs, geometry, qmax)
    cand.to_csv(OUT / "p1-1_可行组批候选.csv", index=False, encoding="utf-8-sig")
    base_raw, base_metric = solve_set_partition(cand, boxes, "N")
    base = annotate_batches(base_raw)
    save_csv(base, "p1-1_第1小问_基准组批.csv")
    save_csv(expand_assignment(base), "p1-1_第1小问_货箱分配.csv")

    # 第2小问：三个单目标 + 三个综合权重方案。
    single_rows = []
    single_solutions = {}
    for key, name in [("N", "架次最少"), ("E", "能耗最少"), ("T", "时间最少")]:
        raw, m = solve_set_partition(cand, boxes, key)
        single_solutions[key] = annotate_batches(raw)
        single_rows.append({"方案": name, **metrics_from(raw), "累计作业时间_h": metrics_from(raw)["累计作业时间_s"] / 3600})

    minN = max(single_rows[0]["架次数"], 1)
    minE = max(single_rows[1]["总能耗_kWh"], 1e-6)
    minT = max(single_rows[2]["累计作业时间_s"], 1e-6)
    weights = [("均衡方案", .333333, .333333, .333333), ("架次优先", .60, .20, .20), ("能耗优先", .20, .60, .20), ("时间优先", .20, .20, .60)]
    trade_rows = list(single_rows)
    balanced = None
    for name, wn, we, wt in weights:
        raw, m = solve_set_partition(cand, boxes, "weighted", {"wN": wn, "wE": we, "wT": wt, "N": minN, "E": minE, "T": minT})
        sol = annotate_batches(raw)
        if name == "均衡方案":
            balanced = sol
            save_csv(sol, "p1-1_第2小问_均衡组批.csv")
        met = metrics_from(raw)
        trade_rows.append({"方案": name, **met, "累计作业时间_h": met["累计作业时间_s"] / 3600})
    tradeoffs = pd.DataFrame(trade_rows)
    tradeoffs["累计作业时间_s"] = tradeoffs["累计作业时间_h"] * 3600
    save_csv(tradeoffs, "p1-1_第2小问_多目标对比.csv")

    # 第3小问：返航余量敏感性。
    sensitivity_rows = []
    for rho in np.array([.10, .15, .20, .30, .40]):
        qt = qmax_table(geometry, specs, float(rho))
        cdt = enumerate_candidates(boxes, services, specs, geometry, qt)
        feasible = True
        try:
            raw_n, _ = solve_set_partition(cdt, boxes, "N")
            raw_b, _ = solve_set_partition(cdt, boxes, "weighted", {"wN": 1/3, "wE": 1/3, "wT": 1/3, "N": max(len(raw_n),1), "E": max(raw_n["往返能耗_kWh"].sum(),1e-6), "T": max(raw_n["累计作业时间_s"].sum(),1e-6)})
        except RuntimeError:
            # 当返航余量过高导致某些单箱也无法安全往返时，记录为不可行
            # 场景，不强行给出虚假的架次结果。
            feasible = False
            raw_n = pd.DataFrame(columns=cdt.columns)
            raw_b = pd.DataFrame(columns=cdt.columns)
        for g in ["A", "B", "C"]:
            sub = qt[qt["机型编号"] == g]
            sensitivity_rows.append({"返航余量": rho, "机型编号": g,
                                     "平均最大安全载荷_kg": sub["最大安全载荷_kg"].mean(),
                                     "最小最大安全载荷_kg": sub["最大安全载荷_kg"].min(),
                                     "能量受限服务区数": int((sub["限制因素"] == "返航安全能量上限").sum()),
                                     "场景是否可行": feasible,
                                     "最少架次": len(raw_n) if feasible else np.nan,
                                     "平衡方案架次数": len(raw_b) if feasible else np.nan,
                                     "平衡方案总能耗_kWh": raw_b["往返能耗_kWh"].sum() if feasible else np.nan,
                                     "平衡方案累计作业时间_s": raw_b["累计作业时间_s"].sum() if feasible else np.nan})
        if abs(rho - base_rho) < 1e-9:
            qt.to_csv(OUT / "p1-1_第3小问_基准余量qmax复核.csv", index=False, encoding="utf-8-sig")
    sensitivity = pd.DataFrame(sensitivity_rows)
    save_csv(sensitivity, "p1-1_第3小问_返航余量敏感性.csv")

    summary = {
        "数据目录": str(DATA), "DEM": str(first_tif()), "服务区数": int(len(services)),
        "货箱数": int(len(boxes)), "基准返航余量": base_rho,
        "第1小问基准方案": base_metric,
        "第2小问均衡方案": metrics_from(balanced),
        "输出目录": str(OUT), "图形目录": str(FIG),
        "说明": "本程序使用附录给定的等效航程反推水平能耗，下降附加能耗按题设取0。"
    }
    with open(OUT / "p1-1_运行摘要.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(OUT / "p1-1_说明.txt", "w", encoding="utf-8") as f:
        f.write("问题一独立求解结果\n")
        f.write("=" * 40 + "\n")
        f.write("第1小问：先按最大安全载荷、体积和能源约束生成可行货箱组，再以架次数最少求基准组批。\n")
        f.write("第2小问：分别求架次、能耗、时间单目标解，并给出均衡、架次优先、能耗优先、时间优先方案。\n")
        f.write("第3小问：在10%至40%返航安全余量场景下重复求解，记录最大载荷、能量受限服务区数和架次变化。\n")
        f.write("所有输出均在p1-1目录内，项目根目录原有文件未修改。\n")

    make_figures(qmax, base, sensitivity, tradeoffs, services)
    print("P1-1完成")
    print("结果目录:", OUT)
    print("图形目录:", FIG)
    print("基准方案:", metrics_from(base_raw))
    print("均衡方案:", metrics_from(balanced))


if __name__ == "__main__":
    main()
