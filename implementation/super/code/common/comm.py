# -*- coding: utf-8 -*-
"""附录 3 通信链路计算与服务状态判定。

链路预算
    P_th^b   = P_sens^b + M^b
    L_max^{a->b} = Pt_a + Gt_a + Gr_b - L_sys - P_th^b
    L_max^{a<->b} = min(L_max^{a->b}, L_max^{b->a})          （双向判定）
传播损耗
    L_FSPL = 32.45 + 20lg f(MHz) + 20lg D(km)
    L_path = L_FSPL + L_obs · b_ij   （b_ij 为地形遮挡变量）
链路可用
    A_ij(t) = 1  <=>  L_path <= L_max^{i<->j}
"""
from __future__ import annotations

import functools
import numpy as np

from .config import TX, P_TH, L_SYS, L_OBS, CARRIER_MHZ, GATEWAY_ANT_HEIGHT
from .dem import get_dem, planar_m

# 载波项常数：32.45 + 20lg(2400)
FSPL_K = 32.45 + 20.0 * np.log10(CARRIER_MHZ)


def fspl(d_m):
    """自由空间传播损耗 (dB)。d_m 为三维直线距离（米）。"""
    d_km = np.maximum(np.asarray(d_m, dtype=float), 1e-6) / 1000.0
    return FSPL_K + 20.0 * np.log10(d_km)


@functools.lru_cache(maxsize=None)
def lmax(a_key: str, b_key: str) -> float:
    """方向 a->b 的最大允许总传播损耗 (dB)。"""
    pt, gt = TX[a_key]
    _, gr = TX[b_key]
    return pt + gt + gr - L_SYS - P_TH


@functools.lru_cache(maxsize=None)
def lmax_bidir(a_key: str, b_key: str) -> float:
    """双向链路门限：两个方向最大允许损耗的较小值 (dB)。"""
    return min(lmax(a_key, b_key), lmax(b_key, a_key))


def link_margin(p_a, p_b, a_key, b_key, dem=None, check_block=True):
    """返回 (可用?, 余量 dB, L_path, 是否遮挡)。余量 = L_max - L_path。"""
    dem = dem or get_dem()
    dx = planar_m(p_a[0], p_a[1], p_b[0], p_b[1])
    dz = p_b[2] - p_a[2]
    D = float(np.hypot(dx, dz))
    blocked = dem.los_blocked(p_a, p_b) if check_block else False
    Lp = float(fspl(D)) + (L_OBS if blocked else 0.0)
    Lm = lmax_bidir(a_key, b_key)
    return (Lp <= Lm), float(Lm - Lp), Lp, bool(blocked)


# --------------------------------------------------------------- 端点位置
def gateway_pos(node_df):
    """固定网关 G01 的三维通信端点位置（O01 坐标 + 地面海拔 + 天线离地高度）。"""
    r = node_df.set_index("id").loc["O01"]
    return (float(r.lon), float(r.lat), float(r.elev) + GATEWAY_ANT_HEIGHT)


def drone_alt_profile(leg, gt):
    """航段上运输无人机的 (t, h) 高度剖面锚点。

    按附录 2 口径：先垂直爬升 -> 水平巡航 -> 垂直下降。
    """
    t_up = leg.h_up / gt["v_up"]
    t_cr = leg.d / gt["vc"]
    t_dn = leg.h_dn / gt["v_down"]
    return dict(t_up=t_up, t_cr=t_cr, t_dn=t_dn, T=t_up + t_cr + t_dn,
                z0=leg.z_cruise - leg.h_up, z1=leg.z_cruise - leg.h_dn,
                zc=leg.z_cruise)


def drone_pos_on_leg(leg, gt, tau):
    """航段内滞后 tau 秒时运输无人机的三维位置 (lon, lat, alt)。

    tau 为相对于该航段开始的秒数，自动截断到 [0, T]。
    """
    p = drone_alt_profile(leg, gt)
    tau = float(np.clip(tau, 0.0, p["T"]))
    lon0, lat0 = _leg_endpoint(leg, "i")
    lon1, lat1 = _leg_endpoint(leg, "j")
    if tau <= p["t_up"]:
        return (lon0, lat0, p["z0"] + gt["v_up"] * tau)
    if tau <= p["t_up"] + p["t_cr"]:
        s = (tau - p["t_up"]) / max(p["t_cr"], 1e-9)
        return (lon0 + (lon1 - lon0) * s, lat0 + (lat1 - lat0) * s, p["zc"])
    s = (tau - p["t_up"] - p["t_cr"]) / max(p["t_dn"], 1e-9)
    return (lon1, lat1, p["zc"] - gt["v_down"] * (tau - p["t_up"] - p["t_cr"]))


# 让 Leg 自己记录端点经纬度，便于恢复位置
def attach_endpoints(leg, lon_i, lat_i, lon_j, lat_j):
    leg.lon_i, leg.lat_i = lon_i, lat_i
    leg.lon_j, leg.lat_j = lon_j, lat_j
    return leg


def _leg_endpoint(leg, which):
    if which == "i":
        return getattr(leg, "lon_i", None), getattr(leg, "lat_i", None)
    return getattr(leg, "lon_j", None), getattr(leg, "lat_j", None)


# --------------------------------------------------------------- 状态判定
def comm_state(drone_pos, gw_pos, relay_pos, dem=None):
    """运输无人机在某一时刻的通信状态。

    返回 (state, detail)：state ∈ {'direct','relay','outage'}。
    """
    dem = dem or get_dem()
    ok_d, m_d, L_d, b_d = link_margin(drone_pos, gw_pos, "U", "G01", dem)
    if ok_d:
        return "direct", dict(margin=m_d, Lpath=L_d, blocked=b_d)
    if relay_pos is not None:
        ok_a, m_a, L_a, b_a = link_margin(drone_pos, relay_pos, "U", "RA", dem)
        ok_b, m_b, L_b, b_b = link_margin(relay_pos, gw_pos, "RB", "G01", dem)
        if ok_a and ok_b:
            return "relay", dict(margin_access=m_a, margin_backhaul=m_b,
                                 blocked_access=b_a, blocked_backhaul=b_b)
        return "outage", dict(margin_direct=m_d, margin_access=m_a, margin_backhaul=m_b)
    return "outage", dict(margin_direct=m_d, Lpath=L_d, blocked=b_d)


def direct_ok(pos, gw_pos, dem=None):
    dem = dem or get_dem()
    ok, m, L, b = link_margin(pos, gw_pos, "U", "G01", dem)
    return ok, m, L, b


if __name__ == "__main__":
    from .data import load_nodes, load_transport_types
    from .physics import Leg, ops_height
    nd = load_nodes()
    gw = gateway_pos(nd)
    print("G01 通信端点:", gw)
    print("Lmax  U<->G01 = %.1f dB" % lmax_bidir("U", "G01"))
    print("Lmax  U<->RA  = %.1f dB" % lmax_bidir("U", "RA"))
    print("Lmax  RB<->G01= %.1f dB" % lmax_bidir("RB", "G01"))
    print("FSPL(1000m) = %.2f dB" % fspl(1000))
    # 最大无遮挡直连距离
    Lm = lmax_bidir("U", "G01")
    d_free = 10 ** ((Lm - FSPL_K) / 20) * 1000
    d_obs = 10 ** ((Lm - FSPL_K - L_OBS) / 20) * 1000
    print("直连距离上限：无遮挡 %.0f m，有遮挡 %.0f m" % (d_free, d_obs))
    Lm2 = lmax_bidir("RB", "G01")
    print("中继回传距离上限：无遮挡 %.0f m，有遮挡 %.0f m" %
          (10 ** ((Lm2 - FSPL_K) / 20) * 1000, 10 ** ((Lm2 - FSPL_K - L_OBS) / 20) * 1000))
    Lm3 = lmax_bidir("U", "RA")
    print("接入距离上限：无遮挡 %.0f m，有遮挡 %.0f m" %
          (10 ** ((Lm3 - FSPL_K) / 20) * 1000, 10 ** ((Lm3 - FSPL_K - L_OBS) / 20) * 1000))
