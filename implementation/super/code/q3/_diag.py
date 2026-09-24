# -*- coding: utf-8 -*-
"""问题三诊断：中继无人机时序是否允许"全覆盖"，以及列池结构与瓶颈。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import q3.q3_solve as Q


def main():
    Q.precompute_all_legs()
    trips, _ = Q.load_q2_trips()
    timelines = Q.build_timelines(trips)
    outages = []
    for tl in timelines:
        for o in Q.outage_intervals(tl):
            o["trip_id"] = tl["trip_id"]
            outages.append(o)
    cand = Q.hover_candidates()
    cover = Q.coverage_matrix(cand, timelines, outages)
    props = Q.gen_proposals(cand, outages, cover)
    print("中继无人机：", Q.REL_FLEET["rid"].tolist())
    print("列池 %d 条" % len(props))
    for p in props:
        p["lead"] = Q.RELAY["t_prep"] + p["out_leg"]["t"] + Q.RELAY["t_link"]
        p["busy_size"] = p["lead"] + p["dur"] + p["back_leg"]["t"] + Q.RELAY["t_turn"]
    print("%-6s %-10s %-10s %-10s %-10s %s" %
          ("c", "dur", "lead", "busy", "s_lo", "s_hi"))
    for p in props[:6]:
        print("%-6d %-10.0f %-10.0f %-10.0f %-10d %d" %
              (p["c"], p["dur"], p["lead"], p["busy_size"],
               p["s_int_lo"], p["s_int_hi"]))
    print("lead 范围 %.0f~%.0f s，busy 范围 %.0f~%.0f s，dur 范围 %.0f~%.0f s" %
          (min(p["lead"] for p in props), max(p["lead"] for p in props),
           min(p["busy_size"] for p in props), max(p["busy_size"] for p in props),
           min(p["dur"] for p in props), max(p["dur"] for p in props)))
    print("中断区间 %d 个，时间跨度 %.0f~%.0f s" %
          (len(outages), min(o["t0"] for o in outages),
           max(o["t1"] for o in outages)))
    print("中继参数：", dict(Q.RELAY))
    print("返航安全能量上限 %.3f kWh；能源组件 %s" % (Q.E_RELAY_LIM, dict(Q.REL_MOD)))
    t_span = max(o["t1"] for o in outages) - min(o["t0"] for o in outages)
    print("中断总时长 %.0f s，时间跨度 %.0f s，2 架中继可用总时长约 %.0f s" %
          (sum(o["t1"] - o["t0"] for o in outages), t_span, 2 * t_span))

    for mc in (None, 3000):
        for tlim in (60, 240):
            t0 = time.time()
            sel, unc, st = Q.milp_set_cover(
                props, len(outages), Q.REL_FLEET["rid"].tolist(),
                time_limit=tlim, max_cols=mc, require_full=True)
            print("require_full max_cols=%s t=%ds -> %s 架次 %s 未覆盖 %d (%.0fs)" %
                  (mc, tlim, st, len(sel) if sel else 0,
                   len(unc) if unc else -1, time.time() - t0))
            if sel:
                for p in sel:
                    print("   c=%d s=%d dur=%.0f cover=%s" %
                          (p["c"], p["t_link_done"], p["dur"], p["cover"]))


if __name__ == "__main__":
    main()
