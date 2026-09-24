# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一 前置计算 + 第1小问（q1_1）

范围（严格对应原题）：
    问题一：单点往返运输能力与货箱组批方案。每个架次采用 O01->Si->O01 的直接
    往返形式，仅服务一个服务区，不允许跨服务区组批，不考虑实体无人机/共享
    电池调度（那是问题二的范畴）。
    前置计算：计算三种机型（A/B/C）在15个服务区执行单点往返任务时的最大安全
    载荷 q_max(g,i)。
    第1小问：在货箱不可拆分、每箱只装一次，且满足载质量、装载体积、返航
    安全能量余量的条件下，确定各服务区的货箱组批方案。

本脚本不做第2小问（架次数/能耗/时间的多指标优化）、不做第3小问（返航余量
敏感性分析）——用户已确认第1小问只需给出一个可行方案，架次数是否最少留给
后续问题处理。

关键建模假设（原题未给出显式公式、需要自行推导，已用 AskUserQuestion 向
用户求证过没有更多隐藏公式；下面的公式已在输出与本文档中明确标注）：
    E_hor(d, q) = d / L_g(q) * E_g_use
        水平巡航能耗：用附录2给出的等效航程包络 L_g(q) 反推"单位距离能耗"，
        因为运输机规格表没有巡航功率列，只有航程与效率列，只能从航程包络反推。
    E_up(h, q)   = (m_empty_g + q) * 9.8 * h / (3.6e6 * eta_climb_g)
        爬升附加能耗：标准 mgh 势能公式，除以规格表给出的"爬升能耗效率"，
        J 换算为 kWh 除以 3.6e6。
    E_down = 0（规格表"下降能耗效率"取0，原题原文注明"表示不单独计算下降
    附加能耗"）。

已逐字核实的原文（非猜测）：
    "计划巡航海拔取该航段所经过 DEM 像元的最高地面高程以上50米...调度中心
    O01 作业高度取其地面海拔，服务区作业高度取其地面海拔以上30米。"

运行方式：
    python q1_1.py
输出（当前目录）：
    q1_1_qmax.csv           45组(机型x服务区)最大安全载荷及限制因素
    q1_1_batches.csv        组批结果（每行一个批次）
    q1_1_box_assignment.csv 每箱对应的批次号（核对用）
    q1_1_summary.txt        汇总统计（UTF-8，中文）
"""

import os
import math

import numpy as np
import pandas as pd
import rasterio
from scipy.optimize import brentq

from q00 import (
    load_nodes,
    load_box_list,
    load_transport_drone,
    planar_distance_km,
    F_DEM_TIF,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

G = 9.8              # m/s^2
J_PER_KWH = 3.6e6    # J
RHO_MARGIN = 0.20    # 返航电量下限（三种机型规格表中均为20）
CRUISE_CLEARANCE_M = 50.0   # 巡航海拔 = 路径最高地面高程 + 50m（原题给定）
SERVICE_WORK_HEIGHT_M = 30.0  # 服务区作业高度 = 地面海拔 + 30m（原题给定）


# ---------------------------------------------------------------------------
# 1. 几何与地形：路径最高地面高程、爬升/下降高度
# ---------------------------------------------------------------------------
def sample_path_max_elev(dem_arr, dem_transform, lon1, lat1, lon2, lat2, min_samples=30):
    """沿 (lon1,lat1)-(lon2,lat2) 直线采样 DEM，返回路径上的最高地面高程(m)。

    DEM 分辨率约30m、CRS 为 EPSG:4326（与节点经纬度一致，已核实，无需重投影）。
    采样点数按距离/30m 像元大小取整，保证覆盖每个像元，且不少于 min_samples。
    """
    dist_km = planar_distance_km(lon1, lat1, lon2, lat2)
    n = max(min_samples, math.ceil(dist_km * 1000.0 / 30.0))
    lons = np.linspace(lon1, lon2, n)
    lats = np.linspace(lat1, lat2, n)
    inv = ~dem_transform
    cols, rows = inv * (lons, lats)
    cols = np.clip(np.round(cols).astype(int), 0, dem_arr.shape[1] - 1)
    rows = np.clip(np.round(rows).astype(int), 0, dem_arr.shape[0] - 1)
    elevs = dem_arr[rows, cols]
    return float(np.max(elevs))


def compute_segment_geometry(o01, services, dem_arr, dem_transform):
    """对每个服务区计算：水平距离、路径最高地面高程、巡航海拔、
    去程爬升/下降高度、返程爬升/下降高度。"""
    rows = []
    for _, s in services.iterrows():
        dist_m = planar_distance_km(o01["经度"], o01["纬度"], s["经度"], s["纬度"]) * 1000.0
        path_max_elev = sample_path_max_elev(
            dem_arr, dem_transform, o01["经度"], o01["纬度"], s["经度"], s["纬度"]
        )
        cruise_alt = path_max_elev + CRUISE_CLEARANCE_M
        elev_o01 = o01["海拔"]
        elev_si_work = s["海拔"] + SERVICE_WORK_HEIGHT_M

        h_up_out = cruise_alt - elev_o01
        h_down_out = cruise_alt - elev_si_work
        h_up_ret = cruise_alt - elev_si_work
        h_down_ret = cruise_alt - elev_o01

        rows.append(dict(
            服务区编号=s["服务区编号"],
            水平距离_m=dist_m,
            路径最高地面高程_m=path_max_elev,
            巡航海拔_m=cruise_alt,
            去程爬升高度_m=h_up_out,
            去程下降高度_m=h_down_out,
            返程爬升高度_m=h_up_ret,
            返程下降高度_m=h_down_ret,
        ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. 能耗模型
# ---------------------------------------------------------------------------
def Lg(q, Qg, L0, LF):
    q = np.clip(q, 0.0, Qg)
    return L0 - (L0 - LF) * (q / Qg) ** 1.5


def e_hor(d, q, Qg, L0, LF, e_use):
    return d / Lg(q, Qg, L0, LF) * e_use


def e_up(h, q, m_empty, eta_climb):
    h = max(h, 0.0)
    return (m_empty + q) * G * h / (J_PER_KWH * eta_climb)


def round_trip_energy(q, geo_row, spec_row):
    """去程(载荷q) + 返程(空载) 的总能耗，下降能耗为0。"""
    Qg, L0, LF = spec_row["最大载货质量"], spec_row["空载标准航程"], spec_row["满载标准航程"]
    e_use, m_empty, eta = spec_row["电池可用能量"], spec_row["含电池空载总质量"], spec_row["爬升能耗效率"]
    d = geo_row["水平距离_m"]

    e_out = e_hor(d, q, Qg, L0, LF, e_use) + e_up(geo_row["去程爬升高度_m"], q, m_empty, eta)
    e_ret = e_hor(d, 0.0, Qg, L0, LF, e_use) + e_up(geo_row["返程爬升高度_m"], 0.0, m_empty, eta)
    return e_out + e_ret


# ---------------------------------------------------------------------------
# 3. 最大安全载荷 q_max(g,i)
# ---------------------------------------------------------------------------
def solve_qmax(geo_df, spec_df):
    results = []
    for _, spec_row in spec_df.iterrows():
        g = spec_row["机型编号"]
        Qg = spec_row["最大载货质量"]
        Vg = spec_row["可用装载体积"]
        e_limit = (1.0 - RHO_MARGIN) * spec_row["电池可用能量"]

        for _, geo_row in geo_df.iterrows():
            def f(q):
                return round_trip_energy(q, geo_row, spec_row) - e_limit

            e_at_0 = f(0.0)
            e_at_Q = f(Qg)

            if e_at_0 > 0:
                q_max = 0.0
                limiting = "energy_infeasible_even_empty"
            elif e_at_Q <= 0:
                q_max = Qg
                limiting = "mass_cap"
            else:
                q_max = brentq(f, 0.0, Qg, xtol=1e-6)
                limiting = "energy_margin"

            results.append(dict(
                机型编号=g,
                服务区编号=geo_row["服务区编号"],
                q_max_kg=q_max,
                可用装载体积_m3=Vg,
                限制因素=limiting,
                水平距离_m=geo_row["水平距离_m"],
                巡航海拔_m=geo_row["巡航海拔_m"],
                往返总能耗_kWh_at_qmax=round_trip_energy(q_max, geo_row, spec_row),
                能量上限_kWh=e_limit,
            ))
    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# 4. 单服务区货箱组批（启发式 Best-Fit Decreasing，跨机型选型）
# ---------------------------------------------------------------------------
def batch_service_area(boxes_i, qmax_lookup, vol_lookup, machine_order):
    """boxes_i: 该服务区的货箱 DataFrame（已按优先顺序排好）。
    qmax_lookup[g]: 该服务区、机型 g 的最大安全载荷(kg)。
    vol_lookup[g]: 机型 g 的可用装载体积(m3)。
    返回: batches (list of dict), assignment (dict 货箱编号 -> 批次号)

    新开批次时的机型选择：若剩余未分配货箱（含当前箱）的总质量/总体积能被
    某个可行机型一次性装完，选其中容量最小的（够用即可，避免过度配置）；
    否则说明剩余需求较大，选容量最大的可行机型以尽量多装、减少后续架次数。
    这只是构造可行解的启发式，不保证架次数最少——架次数优化是第2小问的任务。
    """
    boxes_list = boxes_i.to_dict("records")
    n = len(boxes_list)
    suffix_mass = [0.0] * (n + 1)
    suffix_vol = [0.0] * (n + 1)
    for k in range(n - 1, -1, -1):
        suffix_mass[k] = suffix_mass[k + 1] + boxes_list[k]["单箱质量"]
        suffix_vol[k] = suffix_vol[k + 1] + boxes_list[k]["单箱体积"]

    batches = []  # each: {机型, 箱子列表, 已用质量, 已用体积}
    assignment = {}

    for k, box in enumerate(boxes_list):
        mass, vol = box["单箱质量"], box["单箱体积"]

        best_batch_idx = None
        best_slack = None
        for idx, b in enumerate(batches):
            g = b["机型编号"]
            rem_mass = qmax_lookup[g] - b["已用质量"]
            rem_vol = vol_lookup[g] - b["已用体积"]
            if mass <= rem_mass + 1e-9 and vol <= rem_vol + 1e-9:
                slack = rem_mass - mass
                if best_slack is None or slack < best_slack:
                    best_slack = slack
                    best_batch_idx = idx

        if best_batch_idx is not None:
            b = batches[best_batch_idx]
            b["箱子"].append(box["货箱编号"])
            b["已用质量"] += mass
            b["已用体积"] += vol
            assignment[box["货箱编号"]] = best_batch_idx
            continue

        feasible_types = [
            g for g in machine_order
            if mass <= qmax_lookup[g] + 1e-9 and vol <= vol_lookup[g] + 1e-9
        ]
        if not feasible_types:
            raise ValueError(f"货箱 {box['货箱编号']} (质量{mass}kg/体积{vol}m3) 超出所有机型上限，无法组批")

        remaining_mass, remaining_vol = suffix_mass[k], suffix_vol[k]
        finishers = [
            g for g in feasible_types
            if qmax_lookup[g] + 1e-9 >= remaining_mass and vol_lookup[g] + 1e-9 >= remaining_vol
        ]
        chosen_g = min(finishers, key=lambda g: qmax_lookup[g]) if finishers \
            else max(feasible_types, key=lambda g: qmax_lookup[g])

        batches.append(dict(
            机型编号=chosen_g, 箱子=[box["货箱编号"]],
            已用质量=mass, 已用体积=vol,
        ))
        assignment[box["货箱编号"]] = len(batches) - 1

    return batches, assignment


def run_batching(boxes_df, qmax_df, spec_df):
    vol_lookup = dict(zip(spec_df["机型编号"], spec_df["可用装载体积"]))
    machine_order = list(spec_df["机型编号"])

    boxes_df = boxes_df.copy()
    boxes_df["_是否首批_排序"] = (boxes_df["是否首批保障"] == "是").astype(int)
    boxes_df = boxes_df.sort_values(
        by=["_是否首批_排序", "应急优先系数", "单箱质量"], ascending=[False, False, False]
    )

    batch_rows = []
    assign_rows = []

    for sa in sorted(boxes_df["服务区编号"].unique()):
        boxes_i = boxes_df[boxes_df["服务区编号"] == sa]
        qmax_lookup = {
            row["机型编号"]: row["q_max_kg"]
            for _, row in qmax_df[qmax_df["服务区编号"] == sa].iterrows()
        }

        batches, assignment = batch_service_area(boxes_i, qmax_lookup, vol_lookup, machine_order)

        for local_idx, b in enumerate(batches):
            g = b["机型编号"]
            batch_id = f"{sa}-B{local_idx + 1:02d}"
            batch_rows.append(dict(
                批次编号=batch_id,
                服务区编号=sa,
                机型编号=g,
                箱数=len(b["箱子"]),
                总质量_kg=b["已用质量"],
                总体积_m3=b["已用体积"],
                质量上限_kg=qmax_lookup[g],
                体积上限_m3=vol_lookup[g],
                质量利用率=b["已用质量"] / qmax_lookup[g],
                体积利用率=b["已用体积"] / vol_lookup[g],
                货箱列表="|".join(b["箱子"]),
            ))
            for box_id in b["箱子"]:
                assign_rows.append(dict(货箱编号=box_id, 服务区编号=sa, 批次编号=batch_id, 机型编号=g))

    return pd.DataFrame(batch_rows), pd.DataFrame(assign_rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    o01, services = load_nodes()
    boxes = load_box_list()
    spec, _fleet, _battery = load_transport_drone()

    with rasterio.open(F_DEM_TIF) as src:
        dem_arr = src.read(1)
        dem_transform = src.transform

    geo_df = compute_segment_geometry(o01, services, dem_arr, dem_transform)
    qmax_df = solve_qmax(geo_df, spec)
    qmax_df.to_csv(os.path.join(BASE_DIR, "q1_1_qmax.csv"), index=False, encoding="utf-8-sig")
    print("[saved] q1_1_qmax.csv rows=%d" % len(qmax_df))

    batches_df, assign_df = run_batching(boxes, qmax_df, spec)
    batches_df.to_csv(os.path.join(BASE_DIR, "q1_1_batches.csv"), index=False, encoding="utf-8-sig")
    assign_df.to_csv(os.path.join(BASE_DIR, "q1_1_box_assignment.csv"), index=False, encoding="utf-8-sig")
    print("[saved] q1_1_batches.csv rows=%d" % len(batches_df))
    print("[saved] q1_1_box_assignment.csv rows=%d" % len(assign_df))

    # 校验：箱数、质量、体积总量应与原始货箱清单一致
    assert len(assign_df) == len(boxes), "assignment row count mismatch"
    mass_check = abs(batches_df["总质量_kg"].sum() - boxes["单箱质量"].sum()) < 1e-6
    vol_check = abs(batches_df["总体积_m3"].sum() - boxes["单箱体积"].sum()) < 1e-6
    assert mass_check, "total mass mismatch"
    assert vol_check, "total volume mismatch"
    over_cap = batches_df[
        (batches_df["总质量_kg"] > batches_df["质量上限_kg"] + 1e-6)
        | (batches_df["总体积_m3"] > batches_df["体积上限_m3"] + 1e-6)
    ]
    assert len(over_cap) == 0, "some batch exceeds capacity"

    lines = []
    lines.append("问题一 前置计算 + 第1小问 —— 结果汇总")
    lines.append("=" * 50)
    lines.append("")
    lines.append("一、最大安全载荷 q_max(g,i)（45组，机型A/B/C x 服务区S001-S015）")
    for g in spec["机型编号"]:
        sub = qmax_df[qmax_df["机型编号"] == g]
        n_energy = (sub["限制因素"] == "energy_margin").sum()
        n_mass = (sub["限制因素"] == "mass_cap").sum()
        n_infeasible = (sub["限制因素"] == "energy_infeasible_even_empty").sum()
        lines.append(
            f"  机型{g}: q_max范围 [{sub['q_max_kg'].min():.2f}, {sub['q_max_kg'].max():.2f}] kg; "
            f"能量受限{n_energy}个服务区, 质量受限{n_mass}个服务区, 不可行{n_infeasible}个服务区"
        )
    lines.append("")
    lines.append("二、货箱组批方案（第1小问）")
    lines.append(f"  总箱数: {len(boxes)}  总批次数(架次数): {len(batches_df)}")
    for g in spec["机型编号"]:
        n = (batches_df["机型编号"] == g).sum()
        lines.append(f"  机型{g} 使用批次数: {n}")
    lines.append(f"  平均质量利用率: {batches_df['质量利用率'].mean():.1%}")
    lines.append(f"  平均体积利用率: {batches_df['体积利用率'].mean():.1%}")
    lines.append("")
    lines.append("三、校验结果")
    lines.append(f"  箱数一致: {'通过' if len(assign_df) == len(boxes) else '失败'}")
    lines.append(f"  总质量一致: {'通过' if mass_check else '失败'}")
    lines.append(f"  总体积一致: {'通过' if vol_check else '失败'}")
    lines.append(f"  无超容批次: {'通过' if len(over_cap) == 0 else '失败'}")
    lines.append("")
    lines.append("四、建模假设说明（原题未给出显式公式，本脚本采用的推导公式）")
    lines.append("  E_hor(d,q) = d / L_g(q) * E_g_use   （用等效航程包络反推水平能耗）")
    lines.append("  E_up(h,q)  = (m_empty+q)*9.8*h / (3.6e6*eta_climb)   （标准mgh/效率公式）")
    lines.append("  E_down = 0   （规格表下降能耗效率取0，原题注明不单独计算）")

    with open(os.path.join(BASE_DIR, "q1_1_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("[saved] q1_1_summary.txt")
    print("[done] all checks passed" if (mass_check and vol_check and len(over_cap) == 0) else "[warn] some checks failed")


if __name__ == "__main__":
    main()
