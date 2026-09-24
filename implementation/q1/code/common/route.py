# -*- coding: utf-8 -*-
"""带缓存的航段几何与快速架次评估器（问题二/三共用）。

DEM 沿途最高高程采样代价较高，这里把任意两节点间的航段几何（距离、沿途最高
高程、巡航海拔、爬升/下降高度）一次性缓存，之后架次评估只剩四则运算，
从而支撑 ALNS 上万次的目标函数调用。
"""
from __future__ import annotations

import functools
import itertools

import numpy as np

from .config import G, KWH_J, CRUISE_CLEARANCE, OPS_HEIGHT_S, OPS_HEIGHT_O01
from .data import load_nodes, load_transport_types, load_relay_type, sid_list
from .dem import get_dem, planar_m

NODES = load_nodes().set_index("id")
GTS = load_transport_types()
RELAY = load_relay_type()
SIDS = sid_list()
ALL_IDS = ["O01"] + SIDS


# ------------------------------------------------------------------ 航段缓存
@functools.lru_cache(maxsize=None)
def leg_geom(i: str, j: str):
    """节点 i -> j 的航段几何（含 O01/服务区作业高度差）。"""
    ri, rj = NODES.loc[i], NODES.loc[j]
    dem = get_dem()
    d = planar_m(ri.lon, ri.lat, rj.lon, rj.lat)
    zmax = dem.max_elev_path(ri.lon, ri.lat, rj.lon, rj.lat)
    zc = zmax + CRUISE_CLEARANCE
    oi = ri.elev + (OPS_HEIGHT_O01 if i == "O01" else OPS_HEIGHT_S)
    oj = rj.elev + (OPS_HEIGHT_O01 if j == "O01" else OPS_HEIGHT_S)
    return dict(i=i, j=j, d=float(d), zmax=float(zmax), z_cruise=float(zc),
                ops_i=float(oi), ops_j=float(oj),
                h_up=float(max(0.0, zc - oi)), h_dn=float(max(0.0, zc - oj)),
                lon_i=float(ri.lon), lat_i=float(ri.lat),
                lon_j=float(rj.lon), lat_j=float(rj.lat))


def leg_time(g: str, i: str, j: str, gt=None):
    gt = gt or GTS[g]
    lg = leg_geom(i, j)
    return lg["h_up"] / gt["v_up"] + lg["d"] / gt["vc"] + lg["h_dn"] / gt["v_down"]


def leg_energy(g: str, i: str, j: str, q: float, gt=None):
    """航段能耗 (kWh)：水平按等效航程折算 + 爬升附加。"""
    gt = gt or GTS[g]
    lg = leg_geom(i, j)
    L = equiv_range_fast(gt, q)
    e_hor = lg["d"] / L * gt["Euse"]
    e_up = (gt["m_empty"] + q) * G * lg["h_up"] / gt["eta_up"] / KWH_J
    return e_hor + e_up


def equiv_range_fast(gt, q):
    q = min(max(q, 0.0), gt["Q"])
    L0, LF, Q = gt["L0"], gt["LF"], gt["Q"]
    return L0 - (L0 - LF) / (Q ** 1.5) * (q ** 1.5)


# ------------------------------------------------------------------ 架次评估
def trip_metrics(g, stops, mass_by_stop, n_box_by_stop=None):
    """给定机型、服务区序列与各站投递质量，返回架次的全部指标。

    stops: 有序服务区列表（不含 O01）
    返回 dict：feasible, energy, flight_t, total_t, soc_end, legs, arrival(各站到达时刻)
    """
    gt = GTS[g]
    if not stops:
        return None
    seq = ["O01"] + list(stops) + ["O01"]
    legs, E, T = [], 0.0, 0.0
    total_mass = sum(mass_by_stop.get(s, 0.0) for s in stops)
    q = total_mass
    arrival = {}
    t_cursor = 0.0
    for k, (a, b) in enumerate(zip(seq[:-1], seq[1:])):
        if k > 0:
            # 离开服务区 a 之前完成投递：卸载 a 的质量
            q -= mass_by_stop.get(a, 0.0)
        e = leg_energy(g, a, b, q, gt)
        tl = leg_time(g, a, b, gt)
        legs.append(dict(i=a, j=b, q=q, e=e, t=tl, d=leg_geom(a, b)["d"],
                         z_cruise=leg_geom(a, b)["z_cruise"]))
        E += e
        T += tl
        if b != "O01":
            arrival[b] = T
    # 作业时间：准备 + 装载 + 飞行 + 各站交接
    n_box = sum((n_box_by_stop or {}).get(s, 0) for s in stops)
    T_tot = gt["t_prep"] + n_box * gt["t_box_load"] + T
    off = T
    for s in stops:
        nb = (n_box_by_stop or {}).get(s, 0)
        if nb:
            T_tot += gt["t_hand_base"] + nb * gt["t_hand_box"]
            off += gt["t_hand_base"] + nb * gt["t_hand_box"]
    lim = (1 - gt["rho"]) * gt["Euse"]
    return dict(gtype=g, stops=list(stops), energy=E, flight_t=T, total_t=T_tot,
                soc_end=1.0 - E / gt["Euse"], feasible=E <= lim + 1e-9,
                legs=legs, arrival=arrival, limit=lim, mass=total_mass)


def trip_volume(stops, vol_by_stop):
    return sum(vol_by_stop.get(s, 0.0) for s in stops)


@functools.lru_cache(maxsize=None)
def tsp_order(g, stops_tuple):
    """服务区访问顺序优化：枚举全排列取飞行时间/能耗最小者。

    |stops| <= 4 时直接枚举；更大规模用最近邻 + 2-opt。
    """
    stops = list(stops_tuple)
    if len(stops) <= 1:
        return tuple(stops)
    gt = GTS[g]

    def cost(order):
        seq = ["O01"] + list(order) + ["O01"]
        return sum(leg_time(g, a, b, gt) for a, b in zip(seq[:-1], seq[1:]))

    if len(stops) <= 7:
        best, bo = None, None
        for perm in itertools.permutations(stops):
            c = cost(perm)
            if best is None or c < best:
                best, bo = c, perm
        return tuple(bo)
    # 最近邻 + 2-opt
    cur, rem = ["O01"], set(stops)
    while rem:
        nxt = min(rem, key=lambda s: leg_time(g, cur[-1], s, gt))
        cur.append(nxt)
        rem.discard(nxt)
    order = cur[1:]
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                new = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if cost(new) < cost(order) - 1e-9:
                    order, improved = new, True
    return tuple(order)


def precompute_all_legs():
    """预热所有节点对的航段缓存。"""
    for i, j in itertools.product(ALL_IDS, ALL_IDS):
        if i != j:
            leg_geom(i, j)
    return len(ALL_IDS) * (len(ALL_IDS) - 1)
