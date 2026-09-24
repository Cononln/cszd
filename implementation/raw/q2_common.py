# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题二 共享基础设施（q2_common）

本模块不单独运行，供 q2_1.py（NSGA-II，全局分组编码）、q2_2.py（仿真派单+
优先级权重扫描）两份脚本 import，避免重复实现同一套路径评估与资源调度逻辑。

范围（严格对应原题问题二，不重新推导问题一/三/四的内容）：
    一个架次可以在返回 O01 之前经过一个或多个服务区（O01->Si->Sj->...->O01），
    卸货后载荷单调下降；必须把架次落到 8 架实体无人机 + 共享电池池（同型号
    互换、跨型号不互换）上，电池充电用两段非线性公式，同一资源的任务区间/
    充电区间不能重叠；不考虑通信/中继（问题三范畴）。

复用范围（严格不重新推导、不修改 q00.py / q1_1.py / q1_2_common.py）：
    - 节点数据、货箱清单、机队/电池台账、绘图样式：q00.py。
    - DEM 任意两点最高地面高程采样 sample_path_max_elev、能耗模型 Lg/e_hor/e_up
      （下降能耗恒为0）、返航电量下限 RHO_MARGIN、巡航净空 CRUISE_CLEARANCE_M、
      服务区作业高度加成 SERVICE_WORK_HEIGHT_M：q1_1.py。这些函数本就与"是否
      O01"无关（sample_path_max_elev 是任意两点通用的DEM采样），可以直接套用
      到服务区-服务区航段，不需要改写。
    - 问题一的单站候选枚举与集合划分（q2_2.py 构造多站路线的起点）：
      q1_2_common.py 的 load_base_data/enumerate_candidates/solve_set_partitioning/
      total_metrics/validate_selection。

本模块新增（问题一未涉及的部分）：
    1. build_leg_geometry_table()：把 q1_1.compute_segment_geometry 的"O01<->Si
       单腿几何"推广成"任意两个节点(O01或服务区)之间的单腿几何"，只对16个
       节点的 C(16,2)=120 个无向对做一次DEM采样（方向不同只是爬升/下降互换，
       距离和巡航海拔——路径最高DEM高程+50m——对同一对节点是共用的）。
    2. evaluate_route()：链式计算 O01->stop1->...->stopK->O01 的总能耗（逐腿
       按当前实际载荷精确计算并累加——因为 Lg(q) 凹、e_hor(q) 凸，总能耗与
       卸货顺序相关，不能用问题一的 q_max(g,i) 单点查表，那是纯往返场景下
       解出来的，不适用于多站链）与总时间（起飞时一次性的工位准备+按出发
       总箱数装载，每个停靠点一次性的接收交接+按该点卸货箱数增加交接，逐腿
       飞行时间用该腿自己的距离/爬升/下降）。
    3. best_route_order() / best_type_for_group()：站点数上限 MAX_STOPS=3（依据
       见下），对可行排列全部精确比较取能耗最低者（不是最近邻近似——已验证
       能耗确实与顺序相关），跨机型选能耗最低的可行机型。
    4. decode_group_to_routes()：把一组箱子（可能跨多个服务区、可能超出单个
       机型容量）分解成1条或多条可行路线——递归二分（先按服务区排序再按
       箱子对半拆），直到每个子块能被至少一种机型接受；单箱兜底一定可行
       （问题一已证明每箱都能被至少一种机型单独运走）。
    5. simulate_dispatch()：离散事件资源调度模拟器，两份脚本共用。资源状态
       只维护"每机型一组无人机就绪时间+ID、一组电池就绪时间+ID"（同型号
       电池与机身都是可互换资源池，problem 原文把共享电池池与8架机身分开
       列出，本就是"随取随换"设计，不做固定配对）。无人机架次结束后立即
       就绪（不受电池充电拖慢，否则等于变相把电池和机身重新绑死）；电池
       结束后进入两段非线性充电。派单规则：紧迫覆盖优先于 priority_fn——
       先看每条候选路线的硬限时余量，余量低于安全阈值的强制排到最前面，
       只有在没有紧迫路线时才按 priority_fn 的加权分数选，避免"预设权重
       恰好把一条硬限时路线往后排"这种可避免的违约。
    6. hard_deadline() / compute_objectives()：硬约束判定（首批保障箱看
       首批截止时间，医疗物资箱看期望送达时间，两者互不冲突——已核对首批箱
       的首批截止时间<=期望送达时间恒成立）与四个目标(f1配送及时性/f2
       makespan/f3总能耗/f4架次数)的统一计算，硬约束违反单独返回、不并入
       f1，保持"软目标"与"硬可行性"分离。
    7. 共享绘图：fig_route_map（路线结构图）、fig_resource_gantt（资源甘特图），
       两份脚本都调用，不复制粘贴。

范围裁剪说明（写入两份脚本的 summary.txt，不是偷偷简化）：
    - 单架次最多 MAX_STOPS=3 个停靠服务区：问题一 N=18/15区≈1.2架次每区，
      多数服务区单独就接近满载，3站以上同时满足载重的概率极低，属于有依据
      的搜索空间裁剪，不是任意选取。
"""
import heapq
import math
import os
from itertools import permutations

import numpy as np
import pandas as pd
import rasterio

from q00 import (
    load_nodes, load_box_list, load_transport_drone, planar_distance_km,
    F_DEM_TIF, style_ax, savefig, SURFACE, INK, INK2, MUTED, GRID, BASELINE,
    CAT, DRONE_ORDER, DRONE_COLOR,
)
from q1_1 import (
    sample_path_max_elev, Lg, e_hor, e_up,
    RHO_MARGIN, CRUISE_CLEARANCE_M, SERVICE_WORK_HEIGHT_M,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

O01_ID = "O01"
MAX_STOPS = 3
URGENCY_MARGIN_S = 1800.0  # 硬限时余量低于此值时,强制该路线派单优先(约等于一次平均架次时长)


# ---------------------------------------------------------------------------
# 1. 任意两点间的单腿几何（推广 q1_1.compute_segment_geometry）
# ---------------------------------------------------------------------------
def _node_table(o01, services):
    rows = [dict(编号=O01_ID, 经度=o01["经度"], 纬度=o01["纬度"], 作业海拔=o01["海拔"])]
    for _, s in services.iterrows():
        rows.append(dict(编号=s["服务区编号"], 经度=s["经度"], 纬度=s["纬度"],
                          作业海拔=s["海拔"] + SERVICE_WORK_HEIGHT_M))
    return pd.DataFrame(rows).set_index("编号")


def build_leg_geometry_table(o01, services, dem_arr, dem_transform):
    """预计算所有节点两两之间的单腿几何，返回 dict[(from_id,to_id)] ->
    dict(水平距离_m, 爬升高度_m, 下降高度_m)。每对节点只做一次DEM采样。"""
    nodes = _node_table(o01, services)
    ids = list(nodes.index)
    leg = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            na, nb = nodes.loc[a], nodes.loc[b]
            dist_m = planar_distance_km(na["经度"], na["纬度"], nb["经度"], nb["纬度"]) * 1000.0
            path_max_elev = sample_path_max_elev(
                dem_arr, dem_transform, na["经度"], na["纬度"], nb["经度"], nb["纬度"]
            )
            cruise_alt = path_max_elev + CRUISE_CLEARANCE_M
            leg[(a, b)] = dict(水平距离_m=dist_m,
                                爬升高度_m=cruise_alt - na["作业海拔"],
                                下降高度_m=cruise_alt - nb["作业海拔"])
            leg[(b, a)] = dict(水平距离_m=dist_m,
                                爬升高度_m=cruise_alt - nb["作业海拔"],
                                下降高度_m=cruise_alt - na["作业海拔"])
    return leg


def load_leg_geometry_table():
    """装载节点+DEM并建表——两份脚本各自在 main() 里调用一次。"""
    o01, services = load_nodes()
    with rasterio.open(F_DEM_TIF) as src:
        dem_arr = src.read(1)
        dem_transform = src.transform
    return build_leg_geometry_table(o01, services, dem_arr, dem_transform), o01, services


# ---------------------------------------------------------------------------
# 2. 路线能耗/时间：多站链式计算
# ---------------------------------------------------------------------------
def evaluate_route(stops, boxes_by_stop, spec_row, leg_geo):
    """stops: 有序服务区编号序列(不含O01,隐含起止于O01)。
    boxes_by_stop: {服务区编号: [货箱行dict,...]}，覆盖 stops 里的每个站。
    返回 dict(feasible, reason, E_route_kWh, T_route_s, arrival_rel_s,
    depart_ground_time_s, total_mass_kg, total_vol_m3, n_box)。
    """
    Qg, Vg = spec_row["最大载货质量"], spec_row["可用装载体积"]
    L0, LF = spec_row["空载标准航程"], spec_row["满载标准航程"]
    e_use, m_empty, eta = spec_row["电池可用能量"], spec_row["含电池空载总质量"], spec_row["爬升能耗效率"]
    v_cruise, v_climb, v_desc = spec_row["计划巡航速度"], spec_row["最大爬升速度"], spec_row["最大下降速度"]

    all_boxes = [b for s in stops for b in boxes_by_stop[s]]
    total_mass = sum(b["单箱质量"] for b in all_boxes)
    total_vol = sum(b["单箱体积"] for b in all_boxes)
    if total_mass > Qg + 1e-9 or total_vol > Vg + 1e-9:
        return dict(feasible=False, reason="mass_or_volume_exceeds_cap")

    path = [O01_ID] + list(stops) + [O01_ID]
    cur_mass = total_mass
    energy = 0.0
    t = spec_row["工位固定准备时间"] + spec_row["每箱装载时间"] * len(all_boxes)
    depart_ground_time = t
    arrival_rel = {}

    for k in range(len(path) - 1):
        a, b = path[k], path[k + 1]
        g = leg_geo[(a, b)]
        d = g["水平距离_m"]
        energy += e_hor(d, cur_mass, Qg, L0, LF, e_use) + e_up(g["爬升高度_m"], cur_mass, m_empty, eta)
        t += d / v_cruise + g["爬升高度_m"] / v_climb + g["下降高度_m"] / v_desc
        if b != O01_ID:
            arrival_rel[b] = t
            drop = boxes_by_stop[b]
            t += spec_row["接收点基础交接时间"] + spec_row["每箱增加交接时间"] * len(drop)
            cur_mass -= sum(x["单箱质量"] for x in drop)

    e_limit = (1.0 - RHO_MARGIN) * e_use
    feasible = energy <= e_limit + 1e-9
    return dict(
        feasible=feasible,
        reason=None if feasible else "energy_margin_exceeded",
        E_route_kWh=energy, T_route_s=t,
        arrival_rel_s=arrival_rel, depart_ground_time_s=depart_ground_time,
        total_mass_kg=total_mass, total_vol_m3=total_vol, n_box=len(all_boxes),
    )


def best_route_order(areas, boxes_by_area, spec_row, leg_geo):
    """对 <=MAX_STOPS 个服务区的所有排列精确比较，返回能耗最低的可行结果
    （多带 stops 字段），全不可行返回 None。"""
    areas = list(areas)
    if len(areas) > MAX_STOPS:
        raise ValueError(f"stop count {len(areas)} exceeds MAX_STOPS={MAX_STOPS}")
    best = None
    for order in permutations(areas):
        res = evaluate_route(order, boxes_by_area, spec_row, leg_geo)
        if res["feasible"] and (best is None or res["E_route_kWh"] < best["E_route_kWh"]):
            res = dict(res)
            res["stops"] = order
            best = res
    return best


def best_type_for_group(areas, boxes_by_area, spec_df, leg_geo):
    """跨机型选能耗最低的可行机型(多站场景下更省能耗的机型不一定是容量最小的,
    直接比能耗比"够用选最小"的启发式更可靠)。"""
    best = None
    for _, spec_row in spec_df.iterrows():
        res = best_route_order(areas, boxes_by_area, spec_row, leg_geo)
        if res is not None and (best is None or res["E_route_kWh"] < best["E_route_kWh"]):
            res = dict(res)
            res["机型编号"] = spec_row["机型编号"]
            best = res
    return best


# ---------------------------------------------------------------------------
# 3. 分组解码：一组箱子 -> 1条或多条可行路线
# ---------------------------------------------------------------------------
def build_box_index(boxes_df):
    """一次性把 boxes_df 转成 {货箱编号: 行dict} 纯字典。decode_group_to_routes
    在GA/贪心构造里会被调用成千上万次，用纯字典查找取代按货箱编号反复对
    boxes_df 做布尔筛选(isin)，避免每次调用都产生pandas开销。"""
    return {r["货箱编号"]: r for r in boxes_df.to_dict("records")}


def _decode_chunk(ids, box_index, spec_rows, leg_geo, routes):
    by_area = {}
    for bid in ids:
        b = box_index[bid]
        by_area.setdefault(b["服务区编号"], []).append(b)
    areas = list(by_area.keys())

    if len(areas) <= MAX_STOPS:
        res = _best_type_for_group_rows(areas, by_area, spec_rows, leg_geo)
        if res is not None:
            res["boxes_by_stop"] = by_area
            res["priority_sum"] = sum(b["应急优先系数"] for bs in by_area.values() for b in bs)
            routes.append(res)
            return

    if len(ids) == 1:
        raise RuntimeError(f"单箱 {ids[0]} 在所有机型下都不可行,不应该发生(问题一已证明每箱可行)")
    mid = len(ids) // 2
    _decode_chunk(ids[:mid], box_index, spec_rows, leg_geo, routes)
    _decode_chunk(ids[mid:], box_index, spec_rows, leg_geo, routes)


def _best_type_for_group_rows(areas, boxes_by_area, spec_rows, leg_geo):
    best = None
    for spec_row in spec_rows:
        res = best_route_order(areas, boxes_by_area, spec_row, leg_geo)
        if res is not None and (best is None or res["E_route_kWh"] < best["E_route_kWh"]):
            res = dict(res)
            res["机型编号"] = spec_row["机型编号"]
            best = res
    return best


def decode_group_to_routes(box_ids, box_index, spec_rows, leg_geo, cache=None):
    """box_ids: 一组箱子编号(可能跨多个服务区)。box_index 是 build_box_index()
    产出的纯字典；spec_rows 是 [row for _, row in spec_df.iterrows()] 预先
    转好的列表——两者都在GA循环外算一次，避免热路径里的pandas开销。按
    (服务区,箱质量降序)排序后递归二分修复，保证输出的每条路线都可行。
    cache 可传入跨调用的 dict 做 frozenset(box_ids) -> routes 记忆化，组在
    GA变异下高度重复出现。"""
    key = frozenset(box_ids)
    if cache is not None and key in cache:
        return cache[key]
    ids_sorted = sorted(box_ids, key=lambda bid: (box_index[bid]["服务区编号"], -box_index[bid]["单箱质量"]))
    routes = []
    _decode_chunk(ids_sorted, box_index, spec_rows, leg_geo, routes)
    if cache is not None:
        cache[key] = routes
    return routes


# ---------------------------------------------------------------------------
# 4. 硬约束 + 充电曲线
# ---------------------------------------------------------------------------
def hard_deadline(box_row):
    """首批保障箱看首批截止时间,医疗物资箱看期望送达时间,其余无硬约束
    (期望送达时间只进f1,不是硬约束)。两条规则互不冲突(已核对0违反)。"""
    if box_row.get("是否首批保障") == "是":
        return box_row["首批截止时间"]
    if box_row.get("物资类型") == "医疗物资":
        return box_row["期望送达时间"]
    return None


def charge_time(soc_after, t_full):
    """两段非线性充电时间：从 soc_after 充到100%所需时间。"""
    s = min(max(soc_after, 0.0), 1.0)
    if s < 0.90:
        return t_full * (0.65 * (0.90 - s) / 0.90 + 0.35)
    return t_full * 0.35 * (1.0 - s) / 0.10


# ---------------------------------------------------------------------------
# 5. 离散事件资源调度模拟器
# ---------------------------------------------------------------------------
def simulate_dispatch(routes, fleet_df, battery_df, spec_df, priority_fn,
                       urgency_margin_s=URGENCY_MARGIN_S):
    """routes: decode_group_to_routes/best_type_for_group 产出的路线dict列表,
    每条含 机型编号/E_route_kWh/T_route_s/boxes_by_stop/arrival_rel_s。
    priority_fn(route, now)->float,分数越大越优先派发(只在没有紧迫路线时生效)。
    返回 dict(sorties, box_delivery, drone_events, batt_events)。
    """
    e_use = dict(zip(spec_df["机型编号"], spec_df["电池可用能量"]))
    t_full = dict(zip(battery_df["机型编号"], battery_df["等效完全充电时间"]))
    batt_count = dict(zip(battery_df["机型编号"], battery_df["共享电池组总数"]))

    drone_heap, batt_heap = {}, {}
    for g in DRONE_ORDER:
        d_ids = list(fleet_df[fleet_df["机型编号"] == g]["无人机编号"])
        drone_heap[g] = [(0.0, did) for did in d_ids]
        heapq.heapify(drone_heap[g])
        b_ids = [f"{g}-电池{k + 1:02d}" for k in range(int(batt_count.get(g, 0)))]
        batt_heap[g] = [(0.0, bid) for bid in b_ids]
        heapq.heapify(batt_heap[g])

    def hd_slack(route, now):
        deadlines = [hard_deadline(b) for bs in route["boxes_by_stop"].values() for b in bs
                     if hard_deadline(b) is not None]
        if not deadlines:
            return math.inf
        return min(deadlines) - (now + route["T_route_s"])

    def pick(cands, now):
        urgent = [r for r in cands if hd_slack(r, now) < urgency_margin_s]
        if urgent:
            return min(urgent, key=lambda r: hd_slack(r, now))
        return max(cands, key=lambda r: priority_fn(r, now))

    pending = list(routes)
    sorties, drone_events, batt_events = [], [], []
    box_delivery = {}

    while pending:
        types_present = set(r["机型编号"] for r in pending)
        next_time = {g: max(drone_heap[g][0][0], batt_heap[g][0][0])
                     for g in types_present if drone_heap[g] and batt_heap[g]}
        if not next_time:
            raise RuntimeError("存在无法派发的路线(该机型无实体机身或无电池)")
        now = min(next_time.values())
        g_now = [g for g, tt in next_time.items() if tt <= now + 1e-9]
        cands = [r for r in pending if r["机型编号"] in g_now]
        chosen = pick(cands, now)
        g = chosen["机型编号"]
        pending.remove(chosen)

        d_ready, d_id = heapq.heappop(drone_heap[g])
        b_ready, b_id = heapq.heappop(batt_heap[g])
        start = max(now, d_ready, b_ready)
        end = start + chosen["T_route_s"]
        heapq.heappush(drone_heap[g], (end, d_id))

        soc_after = 1.0 - chosen["E_route_kWh"] / e_use[g]
        chg = charge_time(soc_after, t_full[g])
        heapq.heappush(batt_heap[g], (end + chg, b_id))

        sorties.append(dict(route=chosen, 机型编号=g, 无人机编号=d_id, 电池编号=b_id,
                             start=start, end=end))
        drone_events.append(dict(资源编号=d_id, 类型="飞行", start=start, end=end))
        batt_events.append(dict(资源编号=b_id, 类型="飞行", start=start, end=end))
        batt_events.append(dict(资源编号=b_id, 类型="充电", start=end, end=end + chg))

        for area, t_rel in chosen["arrival_rel_s"].items():
            arrive = start + t_rel
            for b in chosen["boxes_by_stop"][area]:
                box_delivery[b["货箱编号"]] = arrive

    return dict(sorties=sorties, box_delivery=box_delivery,
                drone_events=drone_events, batt_events=batt_events)


# ---------------------------------------------------------------------------
# 6. 目标函数
# ---------------------------------------------------------------------------
def compute_objectives(sim_result, boxes_df):
    box_delivery = sim_result["box_delivery"]
    f1 = 0.0
    violations = []
    for _, b in boxes_df.iterrows():
        bid = b["货箱编号"]
        arrive = box_delivery.get(bid)
        if arrive is None:
            violations.append(dict(货箱编号=bid, 原因="未被任何路线覆盖", 送达=None, 限制=None))
            continue
        f1 += b["应急优先系数"] * max(0.0, arrive - b["期望送达时间"])
        hd = hard_deadline(b)
        if hd is not None and arrive > hd + 1e-6:
            violations.append(dict(货箱编号=bid, 原因="硬约束超时", 送达=arrive, 限制=hd))
    f2 = max((s["end"] for s in sim_result["sorties"]), default=0.0)
    f3 = sum(s["route"]["E_route_kWh"] for s in sim_result["sorties"])
    f4 = len(sim_result["sorties"])
    return dict(f1_及时性=f1, f2_makespan_s=f2, f3_总能耗_kWh=f3, f4_架次数=f4, violations=violations)


# ---------------------------------------------------------------------------
# 7. 共享绘图
# ---------------------------------------------------------------------------
def fig_route_map(routes, o01, services, filename, title):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    ax.scatter([o01["经度"]], [o01["纬度"]], marker="s", s=180, color=INK, zorder=5, label="O01 调度中心")
    ax.scatter(services["经度"], services["纬度"], s=90, color=MUTED, edgecolor=INK, linewidths=0.6,
               zorder=4, label="服务区")
    for _, s in services.iterrows():
        ax.annotate(s["服务区编号"], (s["经度"], s["纬度"]), xytext=(4, 4),
                    textcoords="offset points", fontsize=7.6, color=INK2)

    lonlat = {O01_ID: (o01["经度"], o01["纬度"])}
    for _, s in services.iterrows():
        lonlat[s["服务区编号"]] = (s["经度"], s["纬度"])

    seen_type = set()
    for r in routes:
        g = r["机型编号"]
        path = [O01_ID] + list(r["stops"]) + [O01_ID]
        xs = [lonlat[p][0] for p in path]
        ys = [lonlat[p][1] for p in path]
        lbl = f"{g} 型路线" if g not in seen_type else None
        seen_type.add(g)
        ax.plot(xs, ys, color=DRONE_COLOR[g], linewidth=1.3 + 0.5 * (len(r["stops"]) > 1),
                alpha=0.75, zorder=3, label=lbl)

    style_ax(ax, grid_axis="both")
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.set_title(title, loc="left", fontsize=12.4, fontweight="bold", color=INK)
    ax.legend(loc="best", fontsize=8.6, frameon=False)
    savefig(fig, filename)


def fig_resource_gantt(sim_result, fleet_df, battery_df, filename, title):
    import matplotlib.pyplot as plt
    drone_ids = list(fleet_df["无人机编号"])
    batt_ids = []
    for g in DRONE_ORDER:
        n = int(battery_df.set_index("机型编号").loc[g, "共享电池组总数"]) if g in list(battery_df["机型编号"]) else 0
        batt_ids += [f"{g}-电池{k + 1:02d}" for k in range(n)]
    rows = drone_ids + batt_ids
    y_of = {rid: i for i, rid in enumerate(rows)}

    fig, ax = plt.subplots(figsize=(12.5, 0.32 * len(rows) + 2.2))
    kind_color = {"飞行": CAT[0], "充电": CAT[3]}
    seen_kind = set()
    for ev in sim_result["drone_events"] + sim_result["batt_events"]:
        y = y_of[ev["资源编号"]]
        lbl = ev["类型"] if ev["类型"] not in seen_kind else None
        seen_kind.add(ev["类型"])
        ax.broken_barh([(ev["start"] / 3600.0, (ev["end"] - ev["start"]) / 3600.0)], (y - 0.38, 0.76),
                        color=kind_color[ev["类型"]], label=lbl, zorder=3)

    ax.axhline(len(drone_ids) - 0.5, color=BASELINE, linewidth=1.0, zorder=2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=7.4)
    ax.set_xlabel("时间 (h)")
    style_ax(ax, grid_axis="x")
    ax.set_title(title, loc="left", fontsize=12.4, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    savefig(fig, filename)


# ---------------------------------------------------------------------------
# 自检：多站能耗应严格小于两次单站往返之和；单站结果应与 q1_1/q1_2_common 一致
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from q1_1 import round_trip_energy
    from q1_2_common import load_geo_table, batch_time

    leg_geo, o01, services = load_leg_geometry_table()
    boxes = load_box_list()
    spec_df, fleet_df, battery_df = load_transport_drone()
    geo_table = load_geo_table()

    # 用"最轻的2箱"而不是整区箱子列表——整区箱子(最多15箱)很可能超过单机容量,
    # evaluate_route 会正确判不可行,但自检要比的是数值一致性,不是可行性判定本身。
    sa_list = sorted(boxes["服务区编号"].unique())
    sa1, sa2 = sa_list[0], sa_list[1]

    def light_boxes(sa, n=2):
        sub = boxes[boxes["服务区编号"] == sa].sort_values("单箱质量")
        return sub.head(n).to_dict("records")

    b1, b2 = light_boxes(sa1), light_boxes(sa2)

    def first_feasible_type(areas, by_area):
        for _, row in spec_df.iterrows():
            r = best_route_order(areas, by_area, row, leg_geo)
            if r is not None:
                return row, r
        return None, None

    spec_row, res_single = first_feasible_type([sa1], {sa1: b1})
    assert res_single is not None, f"{sa1} 最轻2箱在所有机型下都不可行,自检数据选取有误"

    # 一致性检查：evaluate_route 单站结果应与 round_trip_energy/batch_time 数值一致
    e_ref = round_trip_energy(res_single["total_mass_kg"], geo_table.loc[sa1], spec_row)
    t_ref = batch_time(len(b1), geo_table.loc[sa1], spec_row)
    print(f"[自检1] 单站能耗: evaluate_route={res_single['E_route_kWh']:.6f}  "
          f"round_trip_energy={e_ref:.6f}  差={abs(res_single['E_route_kWh']-e_ref):.2e}")
    print(f"[自检1] 单站时间: evaluate_route={res_single['T_route_s']:.6f}  "
          f"batch_time={t_ref:.6f}  差={abs(res_single['T_route_s']-t_ref):.2e}")
    assert abs(res_single["E_route_kWh"] - e_ref) < 1e-6, "多站引擎单站退化能耗不一致"
    assert abs(res_single["T_route_s"] - t_ref) < 1e-6, "多站引擎单站退化时间不一致"

    # 三角不等式检查：两站合并能耗应严格小于两次单站往返能耗之和(跨机型取合并后最省能耗的可行机型)
    merge_row, res_multi = first_feasible_type([sa1, sa2], {sa1: b1, sa2: b2})
    if res_multi is not None:
        e_sep = round_trip_energy(sum(x["单箱质量"] for x in b1), geo_table.loc[sa1], merge_row) + \
            round_trip_energy(sum(x["单箱质量"] for x in b2), geo_table.loc[sa2], merge_row)
        print(f"[自检2] 两站合并能耗(机型{merge_row['机型编号']})={res_multi['E_route_kWh']:.4f} kWh  "
              f"两次单站之和(同机型)={e_sep:.4f} kWh  合并更省={res_multi['E_route_kWh'] < e_sep}")
        assert res_multi["E_route_kWh"] < e_sep, "两站合并能耗竟不比分开跑更省,能耗模型或几何表有误"
    else:
        print(f"[自检2] {sa1}+{sa2} 在所有机型下合并都不可行(质量/体积或能量超限),"
              f"跳过合并更省的比较(不影响自检1的正确性结论)")
    print("[done] q2_common 自检完成")
