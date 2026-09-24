# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题一第2小问 三种多目标方法的共享基础设施（q1_2_common）

本模块不单独运行，供 q1_21.py / q1_22.py / q1_23.py 三份脚本 import，避免
重复实现同一套问题结构。

复用范围（严格不重新推导、不修改 q1_1.py）：
    - 能耗模型直接复用 q1_1.py 的 round_trip_energy（内部又用到 Lg/e_hor/e_up）；
    - 每个候选批次的质量硬上限直接读取 q1_1.py 已求解好的 q1_1_qmax.csv
      （q_max(g,i)），不重新调用 brentq 求解；
    - 服务区几何（水平距离、四段爬升/下降高度）从 q1_1_qmax.csv 里已保存的
      "水平距离_m"/"巡航海拔_m"，结合 O01 与各服务区地面海拔反推得到，
      不重新做 DEM 路径采样 —— compute_segment_geometry 本就与机型无关，
      qmax.csv 中同一服务区的这两列在三种机型下本就是同一份值的重复。

本模块新增（第1小问未涉及的部分）：
    - 单架次作业时间模型 batch_time()（工位准备/装箱/飞行/交接四段相加）；
    - 候选批次枚举 enumerate_candidates()：对每个服务区、每种机型，用
      DFS+提前剪枝生成所有可行的（箱子子集）候选批次，并精确计算其
      能耗 E_batch_kWh 与时间 T_batch_s；
    - 集合划分（Set Partitioning）通用求解器 solve_set_partitioning()，
      基于 scipy.optimize.milp 精确求解"每箱恰好被一个候选覆盖"的0-1规划。
"""
import os

import numpy as np
import pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

from q00 import load_nodes, load_box_list, load_transport_drone
from q1_1 import SERVICE_WORK_HEIGHT_M, round_trip_energy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
F_QMAX = os.path.join(BASE_DIR, "q1_1_qmax.csv")


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------
def load_base_data():
    """一次性装载三份脚本都要用到的基础数据。"""
    boxes_df = load_box_list()
    spec_df, _fleet, _battery = load_transport_drone()
    qmax_df = pd.read_csv(F_QMAX, encoding="utf-8-sig")
    qmax_lookup = {(r["机型编号"], r["服务区编号"]): r["q_max_kg"] for _, r in qmax_df.iterrows()}
    geo_table = load_geo_table(qmax_df)
    return boxes_df, spec_df, qmax_lookup, geo_table


def load_geo_table(qmax_df=None):
    """从 q1_1_qmax.csv 已保存的水平距离/巡航海拔反推四段高度，列名对齐
    q1_1.py 的 compute_segment_geometry 输出，供 round_trip_energy/batch_time
    直接复用。"""
    if qmax_df is None:
        qmax_df = pd.read_csv(F_QMAX, encoding="utf-8-sig")
    o01, services = load_nodes()
    geo = qmax_df.drop_duplicates("服务区编号")[["服务区编号", "水平距离_m", "巡航海拔_m"]].copy()
    elev_si_work = dict(zip(services["服务区编号"], services["海拔"] + SERVICE_WORK_HEIGHT_M))
    geo["_elev_si_work"] = geo["服务区编号"].map(elev_si_work)
    geo["去程爬升高度_m"] = geo["巡航海拔_m"] - o01["海拔"]
    geo["返程下降高度_m"] = geo["去程爬升高度_m"]
    geo["去程下降高度_m"] = geo["巡航海拔_m"] - geo["_elev_si_work"]
    geo["返程爬升高度_m"] = geo["去程下降高度_m"]
    return geo.set_index("服务区编号")


# ---------------------------------------------------------------------------
# 新增：单架次作业时间模型
# ---------------------------------------------------------------------------
def batch_time(n_box, geo_row, spec_row):
    """单架次总作业时间 = 工位固定准备 + 逐箱装载 + 往返飞行(爬升+巡航+下降) + 交接。

    巡航速度假设不随载重变化（旋翼机匀速巡航的常见简化），故与 round_trip_energy
    不同，T 只依赖 (机型, 服务区, 箱数)，不依赖具体装载质量。
    """
    d = geo_row["水平距离_m"]
    t_ground = (
        spec_row["工位固定准备时间"] + spec_row["每箱装载时间"] * n_box
        + spec_row["接收点基础交接时间"] + spec_row["每箱增加交接时间"] * n_box
    )
    t_cruise = 2.0 * d / spec_row["计划巡航速度"]
    t_climb = (geo_row["去程爬升高度_m"] + geo_row["返程爬升高度_m"]) / spec_row["最大爬升速度"]
    t_descent = (geo_row["去程下降高度_m"] + geo_row["返程下降高度_m"]) / spec_row["最大下降速度"]
    return t_ground + t_cruise + t_climb + t_descent


# ---------------------------------------------------------------------------
# 新增：候选批次枚举（DFS + 剪枝）
# ---------------------------------------------------------------------------
def _dfs_subsets(boxes_i, cap_mass, cap_vol):
    """枚举满足质量/体积上限的所有非空子集（按索引递增的组合树，天然无重复）。
    一旦部分和超过上限就不再扩展该分支——这是剪枝的关键，避免生成完整 2^n 子集。
    返回 [(chosen_idx_tuple, mass_sum, vol_sum), ...]。
    """
    n = len(boxes_i)
    masses = [b["单箱质量"] for b in boxes_i]
    vols = [b["单箱体积"] for b in boxes_i]
    results = []
    stack = [(0, (), 0.0, 0.0)]
    while stack:
        idx, chosen, mass_sum, vol_sum = stack.pop()
        if chosen:
            results.append((chosen, mass_sum, vol_sum))
        for j in range(idx, n):
            nm, nv = mass_sum + masses[j], vol_sum + vols[j]
            if nm <= cap_mass + 1e-9 and nv <= cap_vol + 1e-9:
                stack.append((j + 1, chosen + (j,), nm, nv))
    return results


def enumerate_candidates(boxes_df, spec_df, geo_table, qmax_lookup):
    """对每个服务区 x 每种机型独立枚举候选批次，精确计算能耗与时间。

    每个候选只由 (总质量, 箱数) 决定其能耗/时间（round_trip_energy 只依赖总质量，
    batch_time 只依赖箱数），具体是哪几个箱子只影响集合划分约束里的覆盖关系。
    """
    rows = []
    for sa in sorted(boxes_df["服务区编号"].unique()):
        boxes_i = boxes_df[boxes_df["服务区编号"] == sa][["货箱编号", "单箱质量", "单箱体积"]].to_dict("records")
        geo_row = geo_table.loc[sa]
        for _, spec_row in spec_df.iterrows():
            g = spec_row["机型编号"]
            cap_mass = qmax_lookup[(g, sa)]
            cap_vol = spec_row["可用装载体积"]
            for chosen, mass_sum, vol_sum in _dfs_subsets(boxes_i, cap_mass, cap_vol):
                nb = len(chosen)
                box_ids = tuple(boxes_i[j]["货箱编号"] for j in chosen)
                rows.append(dict(
                    服务区编号=sa,
                    机型编号=g,
                    货箱列表=box_ids,
                    箱数=nb,
                    总质量_kg=mass_sum,
                    总体积_m3=vol_sum,
                    E_batch_kWh=round_trip_energy(mass_sum, geo_row, spec_row),
                    T_batch_s=batch_time(nb, geo_row, spec_row),
                ))
    if not rows:
        raise RuntimeError("候选批次枚举结果为空，请检查 q1_1_qmax.csv 是否存在")
    df = pd.DataFrame(rows)
    df.insert(0, "候选编号", range(len(df)))
    return df


# ---------------------------------------------------------------------------
# 集合划分（Set Partitioning）通用求解器
# ---------------------------------------------------------------------------
def build_incidence(boxes_df, candidates_df):
    """构造 0/1 关联矩阵 A（箱子 x 候选），A[i,j]=1 表示候选 j 覆盖箱子 i。"""
    box_ids = list(boxes_df["货箱编号"])
    idx = {b: k for k, b in enumerate(box_ids)}
    A = lil_matrix((len(box_ids), len(candidates_df)))
    for j, boxes in enumerate(candidates_df["货箱列表"]):
        for b in boxes:
            A[idx[b], j] = 1.0
    return A.tocsr(), box_ids


def solve_set_partitioning(candidates_df, boxes_df, cost):
    """给定候选池与线性代价向量 cost（长度=候选数），精确求解 0-1 集合划分
    （每箱恰好被一个选中候选覆盖），返回被选中候选在 candidates_df 中的行号数组。
    """
    A, box_ids = build_incidence(boxes_df, candidates_df)
    n = len(candidates_df)
    constraint = LinearConstraint(A, lb=np.ones(len(box_ids)), ub=np.ones(len(box_ids)))
    res = milp(
        c=np.asarray(cost, dtype=float),
        constraints=[constraint],
        integrality=np.ones(n),
        bounds=Bounds(lb=0, ub=1),
    )
    if not res.success:
        raise RuntimeError(f"MILP求解失败: {res.message}")
    return np.where(res.x > 0.5)[0]


def total_metrics(selected_df):
    """选中批次集合的三个总指标：架次数、总能耗(kWh)、总时间(s)。"""
    N = len(selected_df)
    E_total = float(selected_df["E_batch_kWh"].sum())
    T_total = float(selected_df["T_batch_s"].sum())
    return N, E_total, T_total


def validate_selection(selected_df, boxes_df):
    """校验：全部货箱被覆盖且不重复（批次不超容已在候选枚举阶段结构性保证）。"""
    all_boxes = [b for boxes in selected_df["货箱列表"] for b in boxes]
    n_expect = len(boxes_df)
    ok_count = len(all_boxes) == n_expect
    ok_unique = len(set(all_boxes)) == n_expect
    ok = ok_count and ok_unique
    msg = (
        f"箱子覆盖校验: 覆盖{len(all_boxes)}箱/应有{n_expect}箱, "
        f"去重后{len(set(all_boxes))}箱 -> {'通过' if ok else '失败'}"
    )
    return ok, msg
