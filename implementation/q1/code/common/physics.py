# -*- coding: utf-8 -*-
"""附录 2 统一口径下的飞行时间、能耗、SOC 与充电周转模型。

运输无人机
----------
等效航程      L_g(q) = L_g^0 - (L_g^0 - L_g^F)/Q_g^{3/2} · q^{3/2}
水平巡航能耗  E_hor = d / L_g(q) · E_g^use
爬升附加能耗  E_up  = m·g·h+ / (eta_up · 3.6e6)      （下降能耗效率为 0，不计）
航段飞行时间  t     = h+/v_up + d/v_c + h-/v_down
返航安全余量  Σ E <= (1 - rho_g)·E_g^use

中继无人机
----------
巡航能耗 = 巡航功率 × 巡航时间；爬升附加能耗同上（质量取计划起飞总质量）；
通信服务能耗 = (悬停功率 + 通信附加功率) × 服务时长。
"""
from __future__ import annotations

import numpy as np

from .config import (G, KWH_J, CRUISE_CLEARANCE, OPS_HEIGHT_O01,
                     OPS_HEIGHT_S, EPS)
from .dem import get_dem, planar_m


# ==================================================================== 航段
class Leg:
    """两个任务节点之间的一个航段（含航线沿途最高地面高程决定的巡航海拔）。"""

    __slots__ = ("i", "j", "d", "zmax", "z_cruise", "h_up", "h_dn",
                 "lon_i", "lat_i", "lon_j", "lat_j", "ops_i", "ops_j")

    def __init__(self, i, j, lon_i, lat_i, ops_i, lon_j, lat_j, ops_j, dem=None):
        dem = dem or get_dem()
        self.i, self.j = i, j
        self.lon_i, self.lat_i, self.ops_i = lon_i, lat_i, ops_i
        self.lon_j, self.lat_j, self.ops_j = lon_j, lat_j, ops_j
        self.d = planar_m(lon_i, lat_i, lon_j, lat_j)
        self.zmax = dem.max_elev_path(lon_i, lat_i, lon_j, lat_j)
        # 计划巡航海拔：沿途 DEM 最高地面高程以上 50 m
        self.z_cruise = self.zmax + CRUISE_CLEARANCE
        self.h_up = max(0.0, self.z_cruise - ops_i)   # 起点作业高度 -> 巡航海拔
        self.h_dn = max(0.0, self.z_cruise - ops_j)   # 巡航海拔 -> 终点作业高度

    def time(self, gt):
        """航段飞行时间 (s)。gt 为机型参数字典。"""
        return self.h_up / gt["v_up"] + self.d / gt["vc"] + self.h_dn / gt["v_down"]

    def energy(self, gt, q):
        """航段运输能耗 (kWh)，q 为该航段上的有效载荷 (kg)。"""
        L = equiv_range(gt, q)
        e_hor = self.d / L * gt["Euse"]
        m = gt["m_empty"] + q
        e_up = m * G * self.h_up / gt["eta_up"] / KWH_J if gt["eta_up"] > 0 else 0.0
        return e_hor + e_up

    def energy_breakdown(self, gt, q):
        L = equiv_range(gt, q)
        e_hor = self.d / L * gt["Euse"]
        e_up = (gt["m_empty"] + q) * G * self.h_up / gt["eta_up"] / KWH_J
        return e_hor, e_up


def equiv_range(gt, q):
    """机型 gt 携带载荷 q 时的等效航程 L_g(q) (m)。"""
    q = min(max(q, 0.0), gt["Q"])
    L0, LF, Q = gt["L0"], gt["LF"], gt["Q"]
    return L0 - (L0 - LF) / (Q ** 1.5) * (q ** 1.5)


def ops_height(node_row):
    """节点作业高度：O01 取地面海拔，服务区取地面海拔 + 30 m。"""
    if node_row["kind"] == "O":
        return node_row["elev"] + OPS_HEIGHT_O01
    return node_row["elev"] + OPS_HEIGHT_S


# ==================================================================== 架次
class TransportTrip:
    """运输架次 p：O01 -> Si1 -> ... -> Sik -> O01。

    载荷沿航段递减：在服务区 s 投递该站全部货箱后，后续航段载荷减少。
    """

    def __init__(self, node_df, stops, gt, boxes_by_stop=None):
        self.stops = list(stops)
        self.gt = gt
        self.node = node_df.set_index("id")
        self.legs = []
        seq = ["O01"] + self.stops + ["O01"]
        for a, b in zip(seq[:-1], seq[1:]):
            ra, rb = self.node.loc[a], self.node.loc[b]
            self.legs.append(Leg(a, b, ra.lon, ra.lat, ops_height(ra),
                                 rb.lon, rb.lat, ops_height(rb)))
        self.boxes_by_stop = boxes_by_stop or {}
        # 预取每架次唯一服务区（保持顺序）
        self.uniq_stops = list(dict.fromkeys(self.stops))

    def leg_by_nodes(self, a, b):
        for k, leg in enumerate(self.legs):
            if leg.i == a and leg.j == b:
                return k, leg
        return None, None

    # ---------------------------------------------------------- 载荷
    def leg_payloads(self, mass_by_stop):
        """返回每个航段上的剩余载荷 (kg)。

        mass_by_stop: dict 服务区 -> 该站投递总质量。
        """
        seq = self.stops
        out = []
        # 出港航段载荷 = 全部待投递质量
        for k, leg in enumerate(self.legs):
            if k == 0:
                q = sum(mass_by_stop.get(s, 0.0) for s in seq)
            elif k <= len(seq) - 1:
                # 已访问 seq[0..k-1]，剩余 seq[k..]
                q = sum(mass_by_stop.get(s, 0.0) for s in seq[k:])
            else:
                q = 0.0  # 返航段
            out.append(q)
        return out

    def total_energy(self, mass_by_stop):
        qs = self.leg_payloads(mass_by_stop)
        return float(sum(leg.energy(self.gt, q) for leg, q in zip(self.legs, qs)))

    def energy_detail(self, mass_by_stop):
        qs = self.leg_payloads(mass_by_stop)
        rows = []
        for leg, q in zip(self.legs, qs):
            eh, eu = leg.energy_breakdown(self.gt, q)
            rows.append(dict(leg=f"{leg.i}->{leg.j}", d=leg.d, z_cruise=leg.z_cruise,
                             h_up=leg.h_up, h_dn=leg.h_dn, q=q,
                             t=leg.time(self.gt), e_hor=eh, e_up=eu, e=eh + eu))
        return rows

    def flight_time(self, mass_by_stop=None):
        """纯航段飞行时间 (s)（不含装载与交接）。"""
        return float(sum(leg.time(self.gt) for leg in self.legs))

    def total_time(self, mass_by_stop, boxes_by_stop=None):
        """架次总作业时长 (s)。

        = 工位固定准备 + Σ每箱装载 + Σ航段飞行 + Σ服务区(基础交接 + 每箱增加交接)
        """
        bbs = boxes_by_stop if boxes_by_stop is not None else self.boxes_by_stop
        n_box = sum(len(v) for v in bbs.values())
        t = self.gt["t_prep"] + n_box * self.gt["t_box_load"] + self.flight_time()
        for s in self.stops:
            nb = len(bbs.get(s, []))
            if nb:
                t += self.gt["t_hand_base"] + nb * self.gt["t_hand_box"]
        return float(t)

    def max_end_energy(self, gt=None):
        return (1 - (gt or self.gt)["rho"]) * (gt or self.gt)["Euse"]

    # ---------------------------------------------------------- 可行性
    def feasible(self, mass_by_stop, vol_by_stop=None):
        """返回 (可行?, 诊断 dict)。"""
        gt = self.gt
        diag = {}
        # 1) 单站载质量/体积（按"该站一次投递"理解：本站货箱必须能被本架次载完）
        for s in self.stops:
            if mass_by_stop.get(s, 0.0) > gt["Q"] + EPS:
                diag["overload_stop"] = s
                return False, diag
        # 2) 出港时总载质量不得超过最大载货质量
        q0 = sum(mass_by_stop.get(s, 0.0) for s in self.stops)
        if q0 > gt["Q"] + EPS:
            diag["overload_trip"] = q0
            return False, diag
        # 3) 装载体积
        if vol_by_stop is not None:
            v0 = sum(vol_by_stop.get(s, 0.0) for s in self.stops)
            if v0 > gt["V"] + 1e-9:
                diag["overvol_trip"] = v0
                return False, diag
        # 4) 返航安全余量
        E = self.total_energy(mass_by_stop)
        lim = (1 - gt["rho"]) * gt["Euse"]
        diag["energy"] = E
        diag["limit"] = lim
        diag["soc_end"] = 1.0 - E / gt["Euse"]
        if E > lim + 1e-9:
            return False, diag
        return True, diag

    def max_payload(self, return_loads=None):
        """本架次在航线上可携带的最大出港总载荷 (kg)（二分求解）。

        return_loads: dict 服务区 -> 返航前该站投递质量（与出港同值即可）。
        求解 Σ E_i(q_i) <= (1-rho)E_use，其中各航段载荷按投递顺序递减。
        """
        gt = self.gt
        stops = self.stops

        def energy_of(total_q):
            """把 total_q 平均分配到各站（载荷递减形状只取决于总量分配方式）。"""
            if not stops:
                return 0.0
            per = total_q / len(stops)
            mbs = {s: per for s in stops}
            return self.total_energy(mbs)

        lo, hi = 0.0, gt["Q"]
        if energy_of(hi) <= (1 - gt["rho"]) * gt["Euse"]:
            return hi
        for _ in range(60):
            mid = (lo + hi) / 2
            if energy_of(mid) <= (1 - gt["rho"]) * gt["Euse"]:
                lo = mid
            else:
                hi = mid
        return lo


# ==================================================================== 中继
def relay_leg(i, j, lon_i, lat_i, lon_j, lat_j, ops_i, ops_j, rt, dem=None):
    """中继航段（复用同一套爬升/巡航/下降口径，但水平能耗按巡航功率计）。"""
    dem = dem or get_dem()
    d = planar_m(lon_i, lat_i, lon_j, lat_j)
    zmax = dem.max_elev_path(lon_i, lat_i, lon_j, lat_j)
    z_cruise = zmax + CRUISE_CLEARANCE
    h_up = max(0.0, z_cruise - ops_i)
    h_dn = max(0.0, z_cruise - ops_j)
    t = h_up / rt["v_up"] + d / rt["vc"] + h_dn / rt["v_down"]
    e_up = rt["m_takeoff"] * G * h_up / rt["eta_up"] / KWH_J
    e_cru = rt["p_cruise"] * (d / rt["vc"]) / 3600.0
    return dict(d=d, zmax=zmax, z_cruise=z_cruise, h_up=h_up, h_dn=h_dn,
                t=t, e_up=e_up, e_cru=e_cru, e=e_up + e_cru)


def relay_mission_energy(rt, out_leg, back_leg, service_s):
    """中继架次总能耗 (kWh)：去程 + 回程 + 悬停/通信服务。"""
    e_hover = (rt["p_hover"] + rt["p_comm"]) * service_s / 3600.0
    return out_leg["e"] + back_leg["e"] + e_hover, e_hover


def relay_mission_time(rt, out_leg, back_leg, service_s):
    """中继架次总占用时长 (s)：准备 + 去程 + 建链 + 服务 + 回程。"""
    return rt["t_prep"] + out_leg["t"] + rt["t_link"] + service_s + back_leg["t"]


def max_relay_service_time(rt, out_leg, back_leg):
    """在返航电量约束下中继可提供的最大服务时长 (s)。"""
    lim = (1 - rt["rho"]) * rt["Euse"]
    e_fly = out_leg["e"] + back_leg["e"]
    p = rt["p_hover"] + rt["p_comm"]
    if e_fly >= lim:
        return -1.0
    return (lim - e_fly) * 3600.0 / p


# ==================================================================== 充电
def charge_time(t_full, soc):
    """两阶段等效充电模型：SOC=s -> 100% 所需时间 (s)。"""
    s = float(np.clip(soc, 0.0, 1.0))
    if s < 0.90:
        return t_full * (0.65 * (0.90 - s) / 0.90 + 0.35)
    return t_full * 0.35 * (1.0 - s) / 0.10
