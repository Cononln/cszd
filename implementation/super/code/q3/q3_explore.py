# -*- coding: utf-8 -*-
"""问题三（探索）：运输航段上的直连可观性普查 + 中继悬停候选点可行性。

输出 results/q3_explore.txt：各服务区往返航段上直连中断的时间占比、
最大连续中断时长，以及"在航段附近悬停能否恢复通信"的初判。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import RES, GATEWAY_ANT_HEIGHT, RELAY_MAX_HOVER_AGL
from common.data import load_nodes
from common.dem import get_dem
from common.route import SIDS, precompute_all_legs, leg_geom
from common.comm import link_margin, lmax_bidir, FSPL_K
from common.traj import leg_phase, pos_on_leg, gateway_from_nodes

DEM = get_dem()
NODES = load_nodes()
GW = gateway_from_nodes(NODES)


def leg_outage(sid, g="C", dt=10.0):
    """O01->Si->O01 往返全程的直连状态序列。"""
    states, ts = [], []
    for a, b in (("O01", sid), (sid, "O01")):
        lg = leg_geom(a, b)
        p = leg_phase(lg, g)
        n = max(1, int(np.ceil(p["T"] / dt)))
        for m in range(1, n + 1):
            tau = p["T"] * m / n
            pos = pos_on_leg(lg, g, tau)
            ok, mg, Lp, blk = link_margin(pos, GW, "U", "G01", DEM)
            states.append(ok)
            ts.append(mg)
    return np.array(states), np.array(ts)


def main():
    precompute_all_legs()
    out = []
    out.append("Lmax(U<->G01) = %.1f dB,  Lmax(U<->RA) = %.1f dB,  Lmax(RB<->G01) = %.1f dB"
               % (lmax_bidir("U", "G01"), lmax_bidir("U", "RA"), lmax_bidir("RB", "G01")))
    out.append("FSPL_K = %.3f dB" % FSPL_K)
    for a, b in [("U", "G01"), ("U", "RA"), ("RB", "G01")]:
        Lm = lmax_bidir(a, b)
        out.append("  %s<->%s 无遮挡上限 %.0f m，有遮挡上限 %.0f m"
                   % (a, b, 10 ** ((Lm - FSPL_K) / 20) * 1000,
                      10 ** ((Lm - FSPL_K - 10.0) / 20) * 1000))
    out.append("")
    out.append("%-6s %8s %8s %8s %8s %8s" %
               ("sid", "dist", "中断比", "最长段", "最差裕量", "沿途最高"))
    rows = []
    for sid in SIDS:
        ok, mg = leg_outage(sid)
        lg = leg_geom("O01", sid)
        # 最长连续中断
        longest, cur = 0, 0
        for v in ok:
            cur = 0 if v else cur + 1
            longest = max(longest, cur)
        rows.append(dict(sid=sid, dist=lg["d"], zmax=lg["zmax"],
                         outage=float(1 - ok.mean()), longest=longest * 10,
                         worst=float(mg.min())))
        out.append("%-6s %8.0f %7.1f%% %7.0fs %8.1f %8.0f" %
                   (sid, lg["d"], (1 - ok.mean()) * 100, longest * 10,
                    mg.min(), lg["zmax"]))
    out.append("")
    n_out = sum(1 for r in rows if r["outage"] > 0.001)
    out.append("存在直连中断的服务区：%d / %d" % (n_out, len(SIDS)))

    # 悬停候选点可行性初判：沿 O01->Si 航段中点在多档离地高度上试算回传链路
    out.append("")
    out.append("== 沿航段中点的回传链路可行性（离地高度 300 m） ==")
    out.append("%-6s %10s %12s %10s" % ("sid", "中点地面", "中点到G01", "回传裕量"))
    for sid in SIDS:
        lg = leg_geom("O01", sid)
        mlon = (lg["lon_i"] + lg["lon_j"]) / 2
        mlat = (lg["lat_i"] + lg["lat_j"]) / 2
        gz = float(DEM.elev(mlon, mlat))
        pos = (mlon, mlat, gz + RELAY_MAX_HOVER_AGL)
        ok, m, Lp, blk = link_margin(pos, GW, "RB", "G01", DEM)
        d = np.hypot((mlon - GW[0]) * 111320 * np.cos(np.radians(mlat)),
                     (mlat - GW[1]) * 110574)
        out.append("%-6s %10.0f %12.0f %10.1f %s" %
                   (sid, gz, d, m, "OK" if ok else "NG"))

    with open(RES / "q3_explore.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("done")


if __name__ == "__main__":
    main()
