# -*- coding: utf-8 -*-
"""
2026年研究生数学建模竞赛 D题 —— 问题三 共享基础设施（q3_common）

本模块不单独运行，供 q3_1.py（NSGA-II 全局联合优化）、q3_2.py（贪心构造+中继
覆盖分配+派单扫描）两份脚本 import，避免重复实现同一套通信可行性判定/中继
候选生成/联合资源调度逻辑。

范围：在问题二（q2_common.py，只处理运输无人机自身路径/资源调度）之上叠加
"通信保障"维度——运输无人机在爬升/巡航/下降全程必须与固定网关G01保持通信
(直连或经中继无人机接力)，中继无人机自身也要被联合调度(悬停位置/海拔/服务
时段、2机身+6能源组件资源池)。

**关键建模假设清单**（附录3未给出可执行的文字算法/公式时采用的合理默认，
写入两份脚本的 summary.txt，不假装是题目原文）：
    1. 路径损耗用标准自由空间公式 32.44+20log10(d_km)+20log10(f_MHz)。
    2. 地形遮挡按DEM直线遮挡二元判定加10dB(Lobs)，非渐进式菲涅尔区计算。
    3. 中继仅单跳(运输<->中继<->G01)——数据里没有中继<->中继参数，这是数据
       结构决定的结论，不是本模块引入的假设。
    4. 爬升/下降段视为在起讫点水平位置原地垂直升降，巡航段视为定高直线飞行
       ——与 q1_1/q2_common 能耗时间模型本身"爬升高度与水平距离独立叠加"的
       既有假设一致。
    5. 中继悬停位置离散化为"缺口腿水平连线5个分数点 x 6档悬停高度(50-300m)"
       的候选网格，非连续优化。
    6. 相位内任一采样点被遮挡即判定整个相位(爬升/巡航/下降)全程需要中继
       覆盖，偏保守但避免子相位级别的复杂区间追踪。
    7. 中继能耗用"功率 x 时长"模型(巡航/悬停/通信附加功率)，区别于运输的
       Lg(q)航程包线模型——因为附件给中继的是功率参数而非航程包线字段。
    8. 单条路线的中继需求最多归并为2个(位置,时间窗)——对应2架中继机身的
       物理上限；超出则诚实标记为违反，不强行凑单一中继覆盖。
    9. 每次中继任务视为"从O01起飞->到位服务->飞回O01"的完整架次，不做跨
       悬停点的连续repositioning——呼应中继自身"架次周转时间"参数隐含的
       离散架次结构。
"""
import heapq
import math
import os

import numpy as np
import pandas as pd
import rasterio

from q00 import (
    load_comm_params, F_DEM_TIF, planar_distance_km, style_ax, savefig,
    SURFACE, INK, INK2, MUTED, GRID, BASELINE, CAT, DRONE_ORDER, DRONE_COLOR,
)
from q1_1 import e_up, SERVICE_WORK_HEIGHT_M
from q2_common import (
    O01_ID, MAX_STOPS, URGENCY_MARGIN_S, charge_time, hard_deadline, compute_objectives,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODELING_ASSUMPTIONS = [
    "路径损耗用标准自由空间公式 FSPL=32.44+20log10(d_km)+20log10(f_MHz)。",
    "地形遮挡按DEM直线遮挡二元判定加10dB(Lobs)，非渐进式菲涅尔区计算。",
    "中继仅单跳(运输<->中继<->G01)——数据里没有中继<->中继参数，这是数据结构决定的结论，不是假设。",
    "爬升/下降段视为在起讫点水平位置原地垂直升降，巡航段定高直线飞行——与q1_1/q2_common能耗时间模型的既有假设一致。",
    "中继悬停位置离散化为'缺口腿水平连线5个分数点 x 6档悬停高度(50-300m)'的候选网格，非连续优化。",
    "相位内任一采样点被遮挡即判定整个相位(爬升/巡航/下降)全程需要中继覆盖，偏保守但避免子相位区间追踪。",
    "中继能耗用'功率 x 时长'模型，区别于运输的Lg(q)航程包线模型——因为附件给中继的是功率参数而非航程包线字段。",
    "单条路线的中继需求最多归并为2个(位置,时间窗)——对应2架中继机身的物理上限；超出诚实标记为违反。",
    "每次中继任务视为'O01起飞->到位服务->飞回O01'的完整架次，不做跨悬停点的连续repositioning。",
]

CLIMB_DESC_FRACS = (0.15, 0.35, 0.55, 0.75, 0.95)
CRUISE_SAMPLE_STEP_M = 250.0
RELAY_CANDIDATE_FRACS = (0.3, 0.4, 0.5, 0.6, 0.7)
MAX_RELAY_POSITIONS_PER_ROUTE = 2


# ---------------------------------------------------------------------------
# 1. 通信可行性子模块（几何/物理层，与机型无关）
# ---------------------------------------------------------------------------
def load_comm_constants():
    """包一层 q00.load_comm_params()，用 .str.contains(...) 精确取数（写法与
    q00.fig_link_budget 一致），返回可复用的 dict。"""
    comm = load_comm_params()
    Lsys = comm.loc[comm["参数名称"].str.contains("系统损耗"), "参数值"].values[0]
    Lobs = comm.loc[comm["参数名称"].str.contains("地形遮挡"), "参数值"].values[0]
    Psens = comm.loc[comm["参数名称"].str.contains("接收灵敏度"), "参数值"].values[0]
    M = comm.loc[comm["参数名称"].str.contains("衰落裕量"), "参数值"].values[0]
    f_mhz = comm.loc[comm["参数名称"].str.contains("载波频率"), "参数值"].values[0]
    Pth = Psens + M

    def role(name):
        sub = comm[comm["参数类别"] == name]
        pt = sub.loc[sub["参数名称"].str.contains("发射功率"), "参数值"].values[0]
        g = sub.loc[sub["参数名称"].str.contains("天线增益"), "参数值"].values[0]
        return float(pt), float(g)

    gw_pt, gw_g = role("固定网关 G01")
    sub_gw = comm[comm["参数类别"] == "固定网关 G01"]
    gw_h = float(sub_gw.loc[sub_gw["参数名称"].str.contains("天线离地高度"), "参数值"].values[0])

    return dict(
        f_mhz=float(f_mhz), Lsys=float(Lsys), Lobs=float(Lobs), Pth=float(Pth),
        roles=dict(
            运输无人机=role("运输无人机"),
            中继接入端=role("中继接入端"),
            中继回传端=role("中继回传端"),
        ),
        gw=dict(pt=gw_pt, g=gw_g, h_agl=gw_h),
    )


def gw_position(comm, o01):
    """G01固定网关的三维绝对位置(与O01同址，天线绝对高度=地面高程+离地高度)。"""
    return float(o01["经度"]), float(o01["纬度"]), float(o01["海拔"]) + comm["gw"]["h_agl"]


def fspl_db(dist_km, f_mhz):
    dist_km = max(dist_km, 1e-3)
    return 32.44 + 20 * np.log10(dist_km) + 20 * np.log10(f_mhz)


def slant_km(lon1, lat1, alt1, lon2, lat2, alt2):
    horiz_km = planar_distance_km(lon1, lat1, lon2, lat2)
    dz_km = abs(alt2 - alt1) / 1000.0
    return math.hypot(horiz_km, dz_km)


def line_of_sight_clear(dem_arr, dem_transform, lon1, lat1, alt1, lon2, lat2, alt2, min_samples=30):
    """沿两点直线采样DEM，逐点比较地面高程与两端插值出的三维直线高度，全程
    不穿地即True。写法沿用 q1_1.sample_path_max_elev 的坐标变换(inv=~transform
    采样)，区别是不取max而是逐点比较。两端点(frac=0/1)必然贴地，排除在判定
    之外，只看中间点是否被地形挡住（与 CLIMB_DESC_FRACS 避开0/1端点同一考虑）。"""
    dist_km = planar_distance_km(lon1, lat1, lon2, lat2)
    n = max(min_samples, math.ceil(dist_km * 1000.0 / 30.0))
    if n < 3:
        return True
    fracs = np.linspace(0.0, 1.0, n)
    lons = lon1 + (lon2 - lon1) * fracs
    lats = lat1 + (lat2 - lat1) * fracs
    line_alts = alt1 + (alt2 - alt1) * fracs
    inv = ~dem_transform
    cols, rows = inv * (lons, lats)
    cols = np.clip(np.round(cols).astype(int), 0, dem_arr.shape[1] - 1)
    rows = np.clip(np.round(rows).astype(int), 0, dem_arr.shape[0] - 1)
    ground = dem_arr[rows, cols]
    return bool(np.all(line_alts[1:-1] >= ground[1:-1] - 1e-6))


def link_budget_db(role_a, role_b, comm):
    def spec(role):
        if role == "固定网关 G01":
            return comm["gw"]["pt"], comm["gw"]["g"]
        return comm["roles"][role]

    pt_a, g_a = spec(role_a)
    pt_b, g_b = spec(role_b)
    lmax_ab = pt_a + g_a + g_b - comm["Lsys"] - comm["Pth"]
    lmax_ba = pt_b + g_b + g_a - comm["Lsys"] - comm["Pth"]
    return min(lmax_ab, lmax_ba)


def link_ok(lon1, lat1, alt1, lon2, lat2, alt2, role_a, role_b, comm, dem_arr, dem_transform):
    lmax = link_budget_db(role_a, role_b, comm)
    clear = line_of_sight_clear(dem_arr, dem_transform, lon1, lat1, alt1, lon2, lat2, alt2)
    loss = fspl_db(slant_km(lon1, lat1, alt1, lon2, lat2, alt2), comm["f_mhz"]) + (0.0 if clear else comm["Lobs"])
    margin = lmax - loss
    return margin >= 0.0, margin


# ---------------------------------------------------------------------------
# 辅助：DEM装载 + 节点位置表（本地重写，q00.load_dem()不返回transform）
# ---------------------------------------------------------------------------
def load_dem_full():
    with rasterio.open(F_DEM_TIF) as src:
        arr = src.read(1)
        transform = src.transform
        bounds = src.bounds
    return arr, transform, (bounds.left, bounds.right, bounds.bottom, bounds.top)


def _dem_elev_at(dem_arr, dem_transform, lon, lat):
    inv = ~dem_transform
    col, row = inv * (lon, lat)
    col = int(np.clip(round(float(col)), 0, dem_arr.shape[1] - 1))
    row = int(np.clip(round(float(row)), 0, dem_arr.shape[0] - 1))
    return float(dem_arr[row, col])


def build_node_positions(o01, services):
    """节点经纬度 + 作业海拔(与 q2_common._node_table 同口径: O01=原始海拔,
    服务区=海拔+SERVICE_WORK_HEIGHT_M) + 地面海拔(不含作业加成,中继起降用)。"""
    lonlat = {O01_ID: (float(o01["经度"]), float(o01["纬度"]))}
    work_elev = {O01_ID: float(o01["海拔"])}
    ground_elev = {O01_ID: float(o01["海拔"])}
    for _, s in services.iterrows():
        sid = s["服务区编号"]
        lonlat[sid] = (float(s["经度"]), float(s["纬度"]))
        ground_elev[sid] = float(s["海拔"])
        work_elev[sid] = float(s["海拔"]) + SERVICE_WORK_HEIGHT_M
    return lonlat, work_elev, ground_elev


# ---------------------------------------------------------------------------
# 2. 逐腿通信画像
# ---------------------------------------------------------------------------
def leg_phase_points(a, b, node_lonlat, node_work_elev, leg_geo):
    lon_a, lat_a = node_lonlat[a]
    lon_b, lat_b = node_lonlat[b]
    g = leg_geo[(a, b)]
    cruise_alt = node_work_elev[a] + g["爬升高度_m"]
    elev_a, elev_b = node_work_elev[a], node_work_elev[b]

    climb = [(f, lon_a, lat_a, elev_a + (cruise_alt - elev_a) * f) for f in CLIMB_DESC_FRACS]
    descent = [(f, lon_b, lat_b, cruise_alt - (cruise_alt - elev_b) * f) for f in CLIMB_DESC_FRACS]

    dist_m = g["水平距离_m"]
    n_cruise = max(10, math.ceil(dist_m / CRUISE_SAMPLE_STEP_M) + 1)
    cruise_fracs = np.linspace(0.0, 1.0, n_cruise)
    cruise = [(float(f), lon_a + (lon_b - lon_a) * f, lat_a + (lat_b - lat_a) * f, cruise_alt)
              for f in cruise_fracs]
    return dict(climb=climb, cruise=cruise, descent=descent)


def build_comm_profile_table(leg_geo, node_lonlat, node_work_elev, comm, gw_pos, dem_arr, dem_transform):
    """对 leg_geo 里全部有向对(a,b)，逐相位判 运输无人机<->G01 直连是否可行。
    返回 dict[(a,b)] -> dict(climb=Phase, cruise=Phase, descent=Phase)，
    Phase = dict(needs_relay, blocked_points=[(t_frac,lon,lat,alt),...])。"""
    profile = {}
    for (a, b) in leg_geo.keys():
        phases = leg_phase_points(a, b, node_lonlat, node_work_elev, leg_geo)
        leg_profile = {}
        for phase_name, pts in phases.items():
            blocked = []
            for (f, lon, lat, alt) in pts:
                ok, _ = link_ok(lon, lat, alt, gw_pos[0], gw_pos[1], gw_pos[2],
                                 "运输无人机", "固定网关 G01", comm, dem_arr, dem_transform)
                if not ok:
                    blocked.append((f, lon, lat, alt))
            leg_profile[phase_name] = dict(needs_relay=len(blocked) > 0, blocked_points=blocked)
        profile[(a, b)] = leg_profile
    return profile


# ---------------------------------------------------------------------------
# 3. 中继候选位置与覆盖判定
# ---------------------------------------------------------------------------
def build_relay_candidates(comm_profile, node_lonlat, dem_arr, dem_transform, dem_bounds, agl_cap):
    agl_levels = tuple(float(x) for x in np.linspace(50.0, agl_cap, 6))
    needed_legs = set()
    for (a, b), phases in comm_profile.items():
        if any(p["needs_relay"] for p in phases.values()):
            needed_legs.add((a, b))

    left, right, bottom, top = dem_bounds
    seen = set()
    candidates = []
    for (a, b) in needed_legs:
        lon_a, lat_a = node_lonlat[a]
        lon_b, lat_b = node_lonlat[b]
        for frac in RELAY_CANDIDATE_FRACS:
            lon = lon_a + (lon_b - lon_a) * frac
            lat = lat_a + (lat_b - lat_a) * frac
            if not (left <= lon <= right and bottom <= lat <= top):
                continue
            key = (round(lon, 4), round(lat, 4))
            if key in seen:
                continue
            seen.add(key)
            ground = _dem_elev_at(dem_arr, dem_transform, lon, lat)
            for agl in agl_levels:
                candidates.append(dict(lon=lon, lat=lat, agl=agl, alt_abs=ground + agl, ground_elev=ground))
    return candidates


def candidate_covers_phase(candidate, phase, comm, dem_arr, dem_transform, backhaul_ok):
    """候选中继位置要覆盖一个相位：接入链路(运输点<->中继接入端)对该相位全部
    被遮挡采样点都必须ok；回传链路(中继回传端<->G01)只与候选点本身有关、与
    具体相位无关，由调用方(build_phase_coverage)对每个候选只算一次后传入，
    避免586个相位 x 3420个候选时对同一候选重复算2000+次回传链路。"""
    if not phase["needs_relay"]:
        return True
    if not backhaul_ok:
        return False
    for (_, lon, lat, alt) in phase["blocked_points"]:
        ok, _ = link_ok(lon, lat, alt, candidate["lon"], candidate["lat"], candidate["alt_abs"],
                         "运输无人机", "中继接入端", comm, dem_arr, dem_transform)
        if not ok:
            return False
    return True


def build_phase_coverage(comm_profile, relay_candidates, comm, dem_arr, dem_transform, gw_pos):
    """对每个 needs_relay 的 (leg,phase) 预计算哪些候选能覆盖它——一次性全局
    预计算，与具体路线无关，route级解析(resolve_route_relay_requirement)只
    做集合查找，不重复调用link_ok，避免GA热路径里重复算DEM/链路预算。"""
    backhaul_ok = [link_ok(cand["lon"], cand["lat"], cand["alt_abs"],
                            gw_pos[0], gw_pos[1], gw_pos[2],
                            "中继回传端", "固定网关 G01", comm, dem_arr, dem_transform)[0]
                   for cand in relay_candidates]
    coverage = {}
    for (a, b), phases in comm_profile.items():
        for phase_name, ph in phases.items():
            if not ph["needs_relay"]:
                continue
            covering = [i for i, cand in enumerate(relay_candidates)
                        if candidate_covers_phase(cand, ph, comm, dem_arr, dem_transform, backhaul_ok[i])]
            coverage[(a, b, phase_name)] = covering
    return coverage


RELAY_CACHE_PATH = os.path.join(BASE_DIR, "q3_relay_precompute_cache.pkl")


def load_or_build_relay_layer(leg_geo, node_lonlat, node_work_elev, comm, gw_pos, dem_arr, dem_transform,
                               dem_bounds, agl_cap, use_cache=True, verbose=True):
    """comm_profile/relay_candidates/phase_coverage三张表只依赖静态输入数据
    (DEM+几何+通信参数)，与GA染色体/贪心路线无关；q3_1.py和q3_2.py各自的
    main()都要算一遍，加上自检脚本本身，同一份重计算至少要跑3次，每次
    实测在此DEM区域(81%相位需中继)下耗时可达十余分钟。磁盘缓存一次写入，
    后续直接命中，不改变任何计算结果，只省重复的DEM/链路预算开销。"""
    import pickle
    if use_cache and os.path.exists(RELAY_CACHE_PATH):
        with open(RELAY_CACHE_PATH, "rb") as f:
            cached = pickle.load(f)
        if verbose:
            print(f"[中继预计算] 命中磁盘缓存 {RELAY_CACHE_PATH}")
        return cached["comm_profile"], cached["relay_candidates"], cached["phase_coverage"]

    comm_profile = build_comm_profile_table(leg_geo, node_lonlat, node_work_elev, comm, gw_pos,
                                              dem_arr, dem_transform)
    relay_candidates = build_relay_candidates(comm_profile, node_lonlat, dem_arr, dem_transform,
                                                dem_bounds, agl_cap)
    phase_coverage = build_phase_coverage(comm_profile, relay_candidates, comm, dem_arr, dem_transform, gw_pos)
    if use_cache:
        with open(RELAY_CACHE_PATH, "wb") as f:
            pickle.dump(dict(comm_profile=comm_profile, relay_candidates=relay_candidates,
                              phase_coverage=phase_coverage), f)
        if verbose:
            print(f"[中继预计算] 已写入磁盘缓存 {RELAY_CACHE_PATH}")
    return comm_profile, relay_candidates, phase_coverage


# ---------------------------------------------------------------------------
# 4. 路线级中继需求解析
# ---------------------------------------------------------------------------
def route_leg_sequence(route):
    path = [O01_ID] + list(route["stops"]) + [O01_ID]
    return [(path[i], path[i + 1]) for i in range(len(path) - 1)]


def resolve_route_relay_requirement(route, leg_geo, comm_profile, phase_coverage, spec_row):
    """走route对应的有向腿序列，对每条腿的climb/cruise/descent还原相对时间
    窗(与evaluate_route内部的用时累加同一套算法，本函数独立实现，不改
    evaluate_route)，把needs_relay=True的相位收集为待覆盖窗口，再用全局
    phase_coverage做集合运算：优先找单一候选覆盖全部窗口，找不到则贪心按
    覆盖数从多到少选，最多累积到MAX_RELAY_POSITIONS_PER_ROUTE个候选。"""
    v_cruise = spec_row["计划巡航速度"]
    v_climb = spec_row["最大爬升速度"]
    v_desc = spec_row["最大下降速度"]

    t = route["depart_ground_time_s"]
    pending = []
    for (a, b) in route_leg_sequence(route):
        g = leg_geo[(a, b)]
        climb_dur = g["爬升高度_m"] / v_climb
        cruise_dur = g["水平距离_m"] / v_cruise
        descent_dur = g["下降高度_m"] / v_desc
        t0 = t
        t1 = t0 + climb_dur
        t2 = t1 + cruise_dur
        t3 = t2 + descent_dur
        for phase_name, (ts, te) in (("climb", (t0, t1)), ("cruise", (t1, t2)), ("descent", (t2, t3))):
            ph = comm_profile[(a, b)][phase_name]
            if ph["needs_relay"]:
                covering = set(phase_coverage.get((a, b, phase_name), []))
                pending.append(dict(leg=(a, b), phase=phase_name, t_start=ts, t_end=te, covering=covering))
        t = t3
        if b != O01_ID:
            drop = route["boxes_by_stop"][b]
            t += spec_row["接收点基础交接时间"] + spec_row["每箱增加交接时间"] * len(drop)

    if not pending:
        return dict(feasible=True, windows=[], gap=[])

    common = None
    for it in pending:
        common = set(it["covering"]) if common is None else (common & it["covering"])
    if common:
        cid = min(common)
        window = dict(candidate_id=cid, t_start=min(it["t_start"] for it in pending),
                      t_end=max(it["t_end"] for it in pending), items=list(pending))
        return dict(feasible=True, windows=[window], gap=[])

    remaining = list(pending)
    windows = []
    while remaining and len(windows) < MAX_RELAY_POSITIONS_PER_ROUTE:
        freq = {}
        for it in remaining:
            for cid in it["covering"]:
                freq[cid] = freq.get(cid, 0) + 1
        if not freq:
            break
        best_cid = max(sorted(freq.keys()), key=lambda c: freq[c])
        covered = [it for it in remaining if best_cid in it["covering"]]
        windows.append(dict(candidate_id=best_cid, t_start=min(it["t_start"] for it in covered),
                             t_end=max(it["t_end"] for it in covered), items=covered))
        remaining = [it for it in remaining if it not in covered]

    gap = remaining
    return dict(feasible=len(gap) == 0, windows=windows, gap=gap)


def attach_relay_requirements(routes, leg_geo, comm_profile, phase_coverage, spec_df):
    spec_by_type = {row["机型编号"]: row for _, row in spec_df.iterrows()}
    for r in routes:
        spec_row = spec_by_type[r["机型编号"]]
        r["relay_req"] = resolve_route_relay_requirement(r, leg_geo, comm_profile, phase_coverage, spec_row)
    return routes


# ---------------------------------------------------------------------------
# 5. 中继能耗模型（功率 x 时长，区别于运输的Lg(q)航程包线模型——数据决定）
# ---------------------------------------------------------------------------
def relay_leg_energy_kwh(dist_horizontal_m, climb_m, hover_s, relay_active_s, relay_spec_row):
    m_takeoff = relay_spec_row["计划起飞总质量"]
    eta = relay_spec_row["爬升能耗效率"]
    v_cruise = relay_spec_row["计划巡航速度"]
    p_cruise = relay_spec_row["巡航功率"]
    p_hover = relay_spec_row["悬停功率"]
    p_comm = relay_spec_row["通信附加功率"]

    e_climb = e_up(climb_m, 0.0, m_takeoff, eta)
    e_cruise_one_way = p_cruise * (dist_horizontal_m / v_cruise) / 3600.0
    e_hover = p_hover * hover_s / 3600.0
    e_comm = p_comm * relay_active_s / 3600.0
    # 往返一次 = 去程(爬升+巡航) + 悬停+通信 + 返程(巡航，下降能耗恒为0)
    return e_climb + e_cruise_one_way + e_hover + e_comm + e_cruise_one_way


# ---------------------------------------------------------------------------
# 6. 联合派单模拟器
# ---------------------------------------------------------------------------
def simulate_joint_dispatch(routes, fleet_df, battery_df, spec_df,
                             relay_fleet_df, relay_stock_df, relay_spec_row, relay_candidates,
                             o01, priority_fn, urgency_margin_s=URGENCY_MARGIN_S):
    """在 q2_common.simulate_dispatch 的堆资源调度模式上扩展第三种资源：中继。
    运输侧的建堆/pick()逻辑与q2_common.simulate_dispatch一致(就地复制，不
    import私有实现，因为要在同一主循环里和中继堆联动)。每条route需读取其
    route["relay_req"](由attach_relay_requirements预先算好)；若feasible=False
    则照常派发、只记一条通信保障缺口violation，不做中继gate。"""
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

    r_ids = list(relay_fleet_df["中继无人机编号"])
    relay_drone_heap = [(0.0, rid) for rid in r_ids]
    heapq.heapify(relay_drone_heap)
    n_relay_batt = int(relay_stock_df["共享能源组件总数"].values[0])
    relay_batt_heap = [(0.0, f"R-能源组件{k + 1:02d}") for k in range(n_relay_batt)]
    heapq.heapify(relay_batt_heap)

    relay_e_use = float(relay_spec_row["能源组件可用能量"])
    relay_rho_margin = float(relay_spec_row["返航电量下限"]) / 100.0
    relay_e_limit = (1.0 - relay_rho_margin) * relay_e_use
    relay_t_full = float(relay_stock_df["等效完全充电时间"].values[0])
    relay_v_cruise = float(relay_spec_row["计划巡航速度"])
    relay_v_climb = float(relay_spec_row["最大爬升速度"])
    relay_v_desc = float(relay_spec_row["最大下降速度"])
    relay_prep_s = float(relay_spec_row["工位固定准备时间"])
    relay_link_s = float(relay_spec_row["建链时间"])
    relay_turn_s = float(relay_spec_row["架次周转时间"])
    o01_lon, o01_lat, o01_ground = float(o01["经度"]), float(o01["纬度"]), float(o01["海拔"])

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
    relay_sorties, relay_events, relay_batt_events = [], [], []
    comm_gap_violations = []
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

        req = chosen.get("relay_req", dict(feasible=True, windows=[], gap=[]))
        plans = []
        for w in req["windows"]:
            cand = relay_candidates[w["candidate_id"]]
            dist_h = planar_distance_km(o01_lon, o01_lat, cand["lon"], cand["lat"]) * 1000.0
            climb_m = max(cand["alt_abs"] - o01_ground, 0.0)
            cruise_time = dist_h / relay_v_cruise
            climb_time = climb_m / relay_v_climb
            descent_time = climb_m / relay_v_desc
            lead = relay_prep_s + climb_time + cruise_time + relay_link_s
            for _ in range(2):
                r_ready0 = relay_drone_heap[0][0]
                rb_ready0 = relay_batt_heap[0][0]
                r_gate = max(r_ready0, rb_ready0) + lead - w["t_start"]
                if r_gate > start:
                    start = r_gate
            plans.append(dict(window=w, cand=cand, dist_h=dist_h, climb_m=climb_m,
                               cruise_time=cruise_time, climb_time=climb_time,
                               descent_time=descent_time, lead=lead))

        end = start + chosen["T_route_s"]
        heapq.heappush(drone_heap[g], (end, d_id))
        soc_after = 1.0 - chosen["E_route_kWh"] / e_use[g]
        chg = charge_time(soc_after, t_full[g])
        heapq.heappush(batt_heap[g], (end + chg, b_id))

        sorties.append(dict(route=chosen, 机型编号=g, 无人机编号=d_id, 电池编号=b_id, start=start, end=end))
        drone_events.append(dict(资源编号=d_id, 类型="飞行", start=start, end=end))
        batt_events.append(dict(资源编号=b_id, 类型="飞行", start=start, end=end))
        batt_events.append(dict(资源编号=b_id, 类型="充电", start=end, end=end + chg))

        for area, t_rel in chosen["arrival_rel_s"].items():
            arrive = start + t_rel
            for b in chosen["boxes_by_stop"][area]:
                box_delivery[b["货箱编号"]] = arrive

        for rp in plans:
            w = rp["window"]
            r_ready, r_id = heapq.heappop(relay_drone_heap)
            rb_ready, rb_id = heapq.heappop(relay_batt_heap)
            depart = max(start + w["t_start"] - rp["lead"], r_ready, rb_ready)
            service_start = depart + relay_prep_s + rp["climb_time"] + rp["cruise_time"] + relay_link_s
            service_end = start + w["t_end"]
            cruise_back_end = service_end + rp["cruise_time"]
            ground_arrive = cruise_back_end + rp["descent_time"]
            hover_s = max(w["t_end"] - w["t_start"], 0.0)
            e_kwh = relay_leg_energy_kwh(rp["dist_h"], rp["climb_m"], hover_s, hover_s, relay_spec_row)
            energy_ok = e_kwh <= relay_e_limit + 1e-9
            r_next = ground_arrive + relay_turn_s
            heapq.heappush(relay_drone_heap, (r_next, r_id))
            relay_soc_after = 1.0 - e_kwh / relay_e_use
            relay_chg = charge_time(relay_soc_after, relay_t_full)
            heapq.heappush(relay_batt_heap, (ground_arrive + relay_chg, rb_id))
            relay_sorties.append(dict(route=chosen, candidate=rp["cand"], 无人机编号=r_id, 能源组件编号=rb_id,
                                       depart=depart, service_start=service_start, service_end=service_end,
                                       ground_arrive=ground_arrive, E_kWh=e_kwh, energy_ok=energy_ok))
            relay_events.append(dict(资源编号=r_id, 类型="飞行", start=depart, end=ground_arrive))
            relay_batt_events.append(dict(资源编号=rb_id, 类型="飞行", start=depart, end=ground_arrive))
            relay_batt_events.append(dict(资源编号=rb_id, 类型="充电", start=ground_arrive, end=ground_arrive + relay_chg))

        if not req["feasible"]:
            comm_gap_violations.append(dict(route=chosen, gap=req["gap"]))

    return dict(sorties=sorties, box_delivery=box_delivery, drone_events=drone_events, batt_events=batt_events,
                relay_sorties=relay_sorties, relay_events=relay_events, relay_batt_events=relay_batt_events,
                comm_gap_violations=comm_gap_violations)


def compute_objectives_joint(sim_result, boxes_df):
    """f1/box覆盖/硬约束违反直接复用 q2_common.compute_objectives(box_delivery
    结构与q2一致，可直接喂)；再叠加通信保障缺口与中继电量超限两类新violation，
    f2/f3/f4在运输分量基础上叠加中继分量(并拆开报告，供图4用)。"""
    obj = compute_objectives(sim_result, boxes_df)
    relay_sorties = sim_result["relay_sorties"]

    violations = list(obj["violations"])
    for gv in sim_result.get("comm_gap_violations", []):
        violations.append(dict(原因="通信保障缺口", 路线机型=gv["route"]["机型编号"],
                                路线停靠=list(gv["route"]["stops"]), 缺口数=len(gv["gap"])))
    for rs in relay_sorties:
        if not rs.get("energy_ok", True):
            violations.append(dict(原因="中继电量超限", 能耗_kWh=rs["E_kWh"]))

    f2_transport = obj["f2_makespan_s"]
    f2_relay = max((r["ground_arrive"] for r in relay_sorties), default=0.0)
    f3_transport = obj["f3_总能耗_kWh"]
    f3_relay = sum(r["E_kWh"] for r in relay_sorties)
    f4_transport = obj["f4_架次数"]
    f4_relay = len(relay_sorties)

    return dict(
        f1_及时性=obj["f1_及时性"],
        f2_makespan_s=max(f2_transport, f2_relay),
        f3_总能耗_kWh=f3_transport + f3_relay,
        f4_架次数=f4_transport + f4_relay,
        f2_运输_s=f2_transport, f2_中继_s=f2_relay,
        f3_运输_kWh=f3_transport, f3_中继_kWh=f3_relay,
        f4_运输架次=f4_transport, f4_中继架次=f4_relay,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# 7. 通信/联合可视化
# ---------------------------------------------------------------------------
def fig_comm_coverage_map(comm_profile, phase_coverage, node_lonlat, o01, services, chosen_relay, filename, title):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    ax.scatter([o01["经度"]], [o01["纬度"]], marker="s", s=200, color=INK, zorder=6, label="O01/G01")
    ax.scatter(services["经度"], services["纬度"], s=90, color=MUTED, edgecolor=INK, linewidths=0.6,
               zorder=5, label="服务区")
    for _, s in services.iterrows():
        ax.annotate(s["服务区编号"], (s["经度"], s["纬度"]), xytext=(4, 4),
                    textcoords="offset points", fontsize=7.6, color=INK2)

    color_direct, color_relay_ok, color_gap = "#1baf7a", "#eda100", "#e34948"
    seen_labels = set()
    for _, s in services.iterrows():
        sid = s["服务区编号"]
        phases = comm_profile.get((O01_ID, sid))
        if phases is None:
            continue
        needed = [pn for pn, p in phases.items() if p["needs_relay"]]
        if not needed:
            color, lbl = color_direct, "直连安全"
        else:
            gap = any(len(phase_coverage.get((O01_ID, sid, pn), [])) == 0 for pn in needed)
            color, lbl = (color_gap, "需中继(缺口)") if gap else (color_relay_ok, "需中继(已覆盖)")
        show_lbl = lbl if lbl not in seen_labels else None
        seen_labels.add(lbl)
        ax.plot([o01["经度"], s["经度"]], [o01["纬度"], s["纬度"]], color=color, linewidth=1.6,
                alpha=0.85, zorder=3, label=show_lbl)

    for rc in chosen_relay:
        ax.scatter([rc["lon"]], [rc["lat"]], marker="D", s=140, color=CAT[5], edgecolor=INK,
                   linewidths=0.8, zorder=7, label="中继悬停点" if "中继悬停点" not in seen_labels else None)
        seen_labels.add("中继悬停点")
        circ = plt.Circle((rc["lon"], rc["lat"]), 0.01, fill=False, linestyle="--", color=CAT[5],
                           linewidth=1.0, zorder=2)
        ax.add_patch(circ)
        ax.annotate(f"AGL={rc['agl']:.0f}m", (rc["lon"], rc["lat"]), xytext=(6, -10),
                    textcoords="offset points", fontsize=7.2, color=INK2)

    style_ax(ax, grid_axis="both")
    ax.set_xlabel("经度")
    ax.set_ylabel("纬度")
    ax.set_title(title, loc="left", fontsize=12.4, fontweight="bold", color=INK)
    ax.legend(loc="best", fontsize=8.4, frameon=False)
    savefig(fig, filename)


def fig_terrain_los_profile(a, b, node_lonlat, node_work_elev, leg_geo, dem_arr, dem_transform,
                             gw_pos, chosen_candidate, filename, title):
    import matplotlib.pyplot as plt
    lon_a, lat_a = node_lonlat[a]
    lon_b, lat_b = node_lonlat[b]
    g = leg_geo[(a, b)]
    dist_m = g["水平距离_m"]
    cruise_alt = node_work_elev[a] + g["爬升高度_m"]

    n = max(60, math.ceil(dist_m / 30.0))
    fracs = np.linspace(0.0, 1.0, n)
    lons = lon_a + (lon_b - lon_a) * fracs
    lats = lat_a + (lat_b - lat_a) * fracs
    inv = ~dem_transform
    cols, rows = inv * (lons, lats)
    cols = np.clip(np.round(cols).astype(int), 0, dem_arr.shape[1] - 1)
    rows = np.clip(np.round(rows).astype(int), 0, dem_arr.shape[0] - 1)
    ground = dem_arr[rows, cols]
    xs = fracs * dist_m

    fig, ax = plt.subplots(figsize=(11.5, 6.0))
    ax.fill_between(xs, np.min(ground) - 20, ground, color="#d8d4c6", zorder=1, label="地形(DEM)")
    ax.plot(xs, ground, color=MUTED, linewidth=1.0, zorder=2)

    ax.plot([0.0, dist_m], [cruise_alt, cruise_alt], color=CAT[0], linewidth=2.0, zorder=4, label="巡航航线")
    ax.plot([0.0, 0.0], [node_work_elev[a], cruise_alt], color=CAT[0], linewidth=2.0, zorder=4)
    ax.plot([dist_m, dist_m], [cruise_alt, node_work_elev[b]], color=CAT[0], linewidth=2.0, zorder=4)

    vx, vy = lon_b - lon_a, lat_b - lat_a
    denom = vx * vx + vy * vy
    gx_frac = ((gw_pos[0] - lon_a) * vx + (gw_pos[1] - lat_a) * vy) / denom if denom > 0 else 0.0
    gx = gx_frac * dist_m
    ax.scatter([gx], [gw_pos[2]], marker="^", s=140, color=INK, zorder=6, label="G01(投影位置)")
    mid_x, mid_alt = dist_m * 0.5, cruise_alt
    ax.plot([mid_x, gx], [mid_alt, gw_pos[2]], color=CAT[7], linewidth=1.4, linestyle="--", zorder=5,
            label="巡航中点->G01 视线")

    if chosen_candidate is not None:
        cx_frac = ((chosen_candidate["lon"] - lon_a) * vx + (chosen_candidate["lat"] - lat_a) * vy) / denom \
            if denom > 0 else 0.0
        cx = cx_frac * dist_m
        ax.scatter([cx], [chosen_candidate["alt_abs"]], marker="D", s=120, color=CAT[5], zorder=6,
                   label="中继悬停点(投影位置)")
        ax.plot([mid_x, cx], [mid_alt, chosen_candidate["alt_abs"]], color=CAT[5], linewidth=1.2,
                linestyle=":", zorder=5, label="巡航中点->中继 视线")

    style_ax(ax, grid_axis="both")
    ax.set_xlabel(f"沿 {a}->{b} 航线的水平距离 (m)（G01/中继点为投影到该方向轴上的示意位置，非真实同轴）")
    ax.set_ylabel("高度 (m, 海拔)")
    ax.set_title(title, loc="left", fontsize=12.2, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=8.4, frameon=False)
    savefig(fig, filename)


def fig_joint_resource_gantt(sim_result, fleet_df, battery_df, relay_fleet_df, relay_stock_df, filename, title):
    import matplotlib.pyplot as plt
    drone_ids = list(fleet_df["无人机编号"])
    batt_ids = []
    for g in DRONE_ORDER:
        n = int(battery_df.set_index("机型编号").loc[g, "共享电池组总数"]) if g in list(battery_df["机型编号"]) else 0
        batt_ids += [f"{g}-电池{k + 1:02d}" for k in range(n)]
    relay_drone_ids = list(relay_fleet_df["中继无人机编号"])
    n_relay_batt = int(relay_stock_df["共享能源组件总数"].values[0])
    relay_batt_ids = [f"R-能源组件{k + 1:02d}" for k in range(n_relay_batt)]

    rows = drone_ids + batt_ids + relay_drone_ids + relay_batt_ids
    y_of = {rid: i for i, rid in enumerate(rows)}

    fig, ax = plt.subplots(figsize=(12.5, 0.32 * len(rows) + 2.4))
    kind_color = {"飞行": CAT[0], "充电": CAT[3]}
    seen_kind = set()
    for ev in sim_result["drone_events"] + sim_result["batt_events"]:
        y = y_of[ev["资源编号"]]
        lbl = f"运输-{ev['类型']}" if ev["类型"] not in seen_kind else None
        seen_kind.add(ev["类型"])
        ax.broken_barh([(ev["start"] / 3600.0, (ev["end"] - ev["start"]) / 3600.0)], (y - 0.38, 0.76),
                        color=kind_color[ev["类型"]], label=lbl, zorder=3)

    relay_kind_color = {"飞行": CAT[6], "充电": CAT[4]}
    seen_relay_kind = set()
    for ev in sim_result["relay_events"] + sim_result["relay_batt_events"]:
        y = y_of[ev["资源编号"]]
        lbl = f"中继-{ev['类型']}" if ev["类型"] not in seen_relay_kind else None
        seen_relay_kind.add(ev["类型"])
        ax.broken_barh([(ev["start"] / 3600.0, (ev["end"] - ev["start"]) / 3600.0)], (y - 0.38, 0.76),
                        color=relay_kind_color[ev["类型"]], label=lbl, zorder=3)

    ax.axhline(len(drone_ids) - 0.5, color=BASELINE, linewidth=1.0, zorder=2)
    ax.axhline(len(drone_ids) + len(batt_ids) - 0.5, color=INK, linewidth=1.3, zorder=2)
    ax.axhline(len(drone_ids) + len(batt_ids) + len(relay_drone_ids) - 0.5, color=BASELINE, linewidth=1.0, zorder=2)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=7.2)
    ax.set_xlabel("时间 (h)")
    style_ax(ax, grid_axis="x")
    ax.set_title(title, loc="left", fontsize=12.2, fontweight="bold", color=INK)
    ax.legend(loc="upper right", fontsize=8.2, frameon=False, ncol=2)
    savefig(fig, filename)


def fig_fleet_breakdown(obj, filename, title):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    labels = ["运输", "中继"]
    sorties = [obj["f4_运输架次"], obj["f4_中继架次"]]
    energy = [obj["f3_运输_kWh"], obj["f3_中继_kWh"]]
    panels = ((axes[0], sorties, "架次数", "(a) 架次数：运输 vs 中继", "{:.0f}"),
              (axes[1], energy, "能耗 (kWh)", "(b) 能耗：运输 vs 中继", "{:.2f}"))
    for ax, vals, ylabel, subtitle, fmt in panels:
        bars = ax.bar(labels, vals, color=[CAT[0], CAT[6]], width=0.55, zorder=3)
        vmax = max(vals) if vals else 1.0
        for bar, v in zip(bars, vals):
            ax.annotate(fmt.format(v), (bar.get_x() + bar.get_width() / 2, v), xytext=(0, 3),
                        textcoords="offset points", ha="center", fontsize=9, color=INK)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, vmax * 1.2 if vmax > 0 else 1.0)
        style_ax(ax, grid_axis="y")
        ax.set_title(subtitle, fontsize=10.2, loc="left", color=INK)
    fig.suptitle(title, fontsize=12.6, fontweight="bold", color=INK, x=0.02, y=0.99, ha="left", va="top")
    fig.subplots_adjust(top=0.82, bottom=0.13, wspace=0.3)
    savefig(fig, filename)


# ---------------------------------------------------------------------------
# 自检：构建通信/中继全部预计算表并打印规模，供两份脚本运行前的快速诊断
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time
    from q00 import load_nodes, load_relay_drone
    from q2_common import load_leg_geometry_table

    t0 = time.time()
    leg_geo, o01, services = load_leg_geometry_table()
    comm = load_comm_constants()
    gw_pos = gw_position(comm, o01)
    dem_arr, dem_transform, dem_bounds = load_dem_full()
    node_lonlat, node_work_elev, node_ground_elev = build_node_positions(o01, services)
    relay_spec_df, relay_fleet_df, relay_stock_df = load_relay_drone()
    relay_spec_row = relay_spec_df.iloc[0]

    print(f"[通信常量] f={comm['f_mhz']:.0f}MHz Lsys={comm['Lsys']}dB Lobs={comm['Lobs']}dB Pth={comm['Pth']}dBm")
    print(f"[G01位置] lon={gw_pos[0]:.6f} lat={gw_pos[1]:.6f} alt_abs={gw_pos[2]:.1f}m")

    t1 = time.time()
    comm_profile, relay_candidates, phase_coverage = load_or_build_relay_layer(
        leg_geo, node_lonlat, node_work_elev, comm, gw_pos, dem_arr, dem_transform, dem_bounds,
        float(relay_spec_row["最大悬停离地高度"]), use_cache=True)
    n_phase_total = sum(len(v) for v in comm_profile.values())
    n_need_relay = sum(1 for v in comm_profile.values() for p in v.values() if p["needs_relay"])
    n_gap = sum(1 for v in phase_coverage.values() if len(v) == 0)
    print(f"[通信画像] 有向腿数={len(comm_profile)}  相位总数={n_phase_total}  需中继相位数={n_need_relay}")
    print(f"[中继候选] 候选点数={len(relay_candidates)}")
    print(f"[覆盖预计算] 需覆盖相位数={len(phase_coverage)}  其中零候选覆盖(硬缺口)={n_gap}"
          f"  三表合计用时={time.time()-t1:.1f}s")
    print(f"[done] q3_common 自检完成，总用时={time.time()-t0:.1f}s")
