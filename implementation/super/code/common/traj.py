# -*- coding: utf-8 -*-
"""运输/中继无人机三维轨迹采样与通信状态时序（问题三共用）。

按附录 2 口径，航段分为"垂直爬升 → 水平巡航 → 垂直下降"三段，
这里给出任意航段上任意时刻的三维位置解析式，用于逐时刻链路预算校验。
"""
from __future__ import annotations

import numpy as np

from .comm import comm_state, link_margin
from .dem import get_dem
from .route import GTS, leg_geom

DEM = get_dem()

PHASES = ("爬升", "巡航", "下降", "投送")


def leg_phase(lg, g):
    """航段各阶段时长与高度锚点。"""
    gt = GTS[g]
    t_up = lg["h_up"] / gt["v_up"]
    t_cr = lg["d"] / gt["vc"]
    t_dn = lg["h_dn"] / gt["v_down"]
    return dict(t_up=t_up, t_cr=t_cr, t_dn=t_dn, T=t_up + t_cr + t_dn,
                z0=lg["ops_i"], zc=lg["z_cruise"], z1=lg["ops_j"])


def pos_on_leg(lg, g, tau):
    """航段 i->j 上滞后 tau 秒时的三维位置 (lon, lat, alt)。"""
    p = leg_phase(lg, g)
    tau = min(max(float(tau), 0.0), p["T"])
    if tau <= p["t_up"]:
        return (lg["lon_i"], lg["lat_i"], p["z0"] + GTS[g]["v_up"] * tau)
    if tau <= p["t_up"] + p["t_cr"]:
        s = (tau - p["t_up"]) / max(p["t_cr"], 1e-9)
        return (lg["lon_i"] + (lg["lon_j"] - lg["lon_i"]) * s,
                lg["lat_i"] + (lg["lat_j"] - lg["lat_i"]) * s, p["zc"])
    return (lg["lon_j"], lg["lat_j"],
            p["zc"] - GTS[g]["v_down"] * (tau - p["t_up"] - p["t_cr"]))


def trip_phases(stops, g, nbox_by_stop):
    """把一个运输架次的完整时间轴切成若干"通信阶段"片段。

    返回 list of dict(phase, t0, t1, lon, lat, alt)：t 为相对架次开始的秒数。
    仅包含题目要求保持连续通信的阶段（爬升/巡航/下降/投送），
    O01 停机坪的准备与装载不列入。
    """
    gt = GTS[g]
    n_box = sum(nbox_by_stop.values())
    seq = ["O01"] + list(stops) + ["O01"]
    t = gt["t_prep"] + n_box * gt["t_box_load"]
    segs = []
    for a, b in zip(seq[:-1], seq[1:]):
        lg = leg_geom(a, b)
        p = leg_phase(lg, g)
        if p["t_up"] > 1e-6:
            segs.append(dict(phase="爬升", t0=t, t1=t + p["t_up"],
                             lon0=lg["lon_i"], lat0=lg["lat_i"],
                             lon1=lg["lon_i"], lat1=lg["lat_i"],
                             z0=p["z0"], z1=p["zc"], lg=lg, g=g))
            t += p["t_up"]
        if p["t_cr"] > 1e-6:
            segs.append(dict(phase="巡航", t0=t, t1=t + p["t_cr"],
                             lon0=lg["lon_i"], lat0=lg["lat_i"],
                             lon1=lg["lon_j"], lat1=lg["lat_j"],
                             z0=p["zc"], z1=p["zc"], lg=lg, g=g))
            t += p["t_cr"]
        if p["t_dn"] > 1e-6:
            segs.append(dict(phase="下降", t0=t, t1=t + p["t_dn"],
                             lon0=lg["lon_j"], lat0=lg["lat_j"],
                             lon1=lg["lon_j"], lat1=lg["lat_j"],
                             z0=p["zc"], z1=p["z1"], lg=lg, g=g))
            t += p["t_dn"]
        if b != "O01":
            nb = nbox_by_stop.get(b, 0)
            if nb:
                dh = gt["t_hand_base"] + nb * gt["t_hand_box"]
                segs.append(dict(phase="投送", t0=t, t1=t + dh,
                                 lon0=lg["lon_j"], lat0=lg["lat_j"],
                                 lon1=lg["lon_j"], lat1=lg["lat_j"],
                                 z0=p["z1"], z1=p["z1"], lg=lg, g=g))
                t += dh
    return segs


def sample_segment(seg, dt=15.0):
    """对单个阶段片段按 dt 采样，返回 (t, lon, lat, alt) 数组。"""
    t0, t1 = seg["t0"], seg["t1"]
    n = max(2, int(np.ceil((t1 - t0) / dt)) + 1)
    ts = np.linspace(t0, t1, n)
    s = (ts - t0) / max(t1 - t0, 1e-9)
    lon = seg["lon0"] + (seg["lon1"] - seg["lon0"]) * s
    lat = seg["lat0"] + (seg["lat1"] - seg["lat0"]) * s
    alt = seg["z0"] + (seg["z1"] - seg["z0"]) * s
    return ts, lon, lat, alt


def trip_timeline(stops, g, nbox_by_stop, start=0.0, dt=15.0):
    """整架次的通信阶段采样（绝对时刻）。

    返回 dict(t, lon, lat, alt, phase, seg_id)，按时间升序。
    """
    ts, lons, lats, alts, phs, segs_id = [], [], [], [], [], []
    segs = trip_phases(stops, g, nbox_by_stop)
    for k, seg in enumerate(segs):
        t, lo, la, al = sample_segment(seg, dt)
        ts.append(t + start)
        lons.append(lo)
        lats.append(la)
        alts.append(al)
        phs.extend([seg["phase"]] * len(t))
        segs_id.extend([k] * len(t))
    return dict(t=np.concatenate(ts), lon=np.concatenate(lons),
                lat=np.concatenate(lats), alt=np.concatenate(alts),
                phase=np.array(phs), seg_id=np.array(segs_id))


# ------------------------------------------------------------ 网关与链路
def gateway_from_nodes(nodes_df):
    from .config import GATEWAY_ANT_HEIGHT
    r = nodes_df.set_index("id").loc["O01"]
    return (float(r.lon), float(r.lat), float(r.elev) + GATEWAY_ANT_HEIGHT)


def direct_margin_series(lon, lat, alt, gw):
    """逐采样点的直连链路余量 (dB)。"""
    out = np.empty(len(lon))
    for k in range(len(lon)):
        ok, m, Lp, blk = link_margin((lon[k], lat[k], alt[k]), gw, "U", "G01", DEM)
        out[k] = m
    return out


def access_margin_series(lon, lat, alt, hover):
    """逐采样点对某一中继悬停位置的接入链路余量 (dB)。"""
    out = np.empty(len(lon))
    for k in range(len(lon)):
        ok, m, Lp, blk = link_margin((lon[k], lat[k], alt[k]), hover, "U", "RA", DEM)
        out[k] = m
    return out
