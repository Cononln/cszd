# -*- coding: utf-8 -*-
"""问题三通信参数灵敏度分析。

在问题二运输方案（架次时序）固定不变的前提下，扫描两项通信参数：
    衰落裕量 M        P_th = P_sens + M，默认 8 dB
    遮挡附加损耗 L_obs，默认 10 dB
对每个参数组合重新逐时刻判定链路状态，统计中断段数与累计中断时长。

本脚本只做"重算中断"，不重新优化中继调度，因此是纯粹的参数灵敏度度量：
它回答的是"通信口径放宽或收紧后，通信保障需求会怎么变"。

运行： python code/q3/q3_sensitivity.py
输出： results/q3_sensitivity.csv, results/q3_sensitivity.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import common.comm as COMM
import common.config as CFG
import q3.q3_solve as Q

RES = ROOT / "results"


def recompute_outages(trips):
    """按当前 COMM 模块内的 P_TH / L_OBS 重算中断区间。"""
    COMM.lmax.cache_clear()
    COMM.lmax_bidir.cache_clear()
    timelines = Q.build_timelines(trips)
    out = []
    for tl in timelines:
        for o in Q.outage_intervals(tl):
            o["trip_id"] = tl["trip_id"]
            out.append(o)
    return out


def main():
    Q.precompute_all_legs()
    trips, _ = Q.load_q2_trips()

    base_pth = CFG.P_TH
    base_lobs = COMM.L_OBS
    p_sens = CFG.P_SENS if hasattr(CFG, "P_SENS") else base_pth - 8.0
    print("基准：P_th = %.0f dBm，L_obs = %.0f dB" % (base_pth, base_lobs))

    rows = []
    # ---- 衰落裕量扫描（固定 L_obs = 基准） ----
    for m in (4.0, 6.0, 8.0, 10.0, 12.0, 14.0):
        COMM.P_TH = p_sens + m
        CFG.P_TH = COMM.P_TH
        COMM.L_OBS = base_lobs
        outs = recompute_outages(trips)
        rows.append(dict(
            param="M", value=m, L_obs=base_lobs, P_th=COMM.P_TH,
            n_seg=len(outs), total_s=round(sum(o["t1"] - o["t0"] for o in outs), 1),
            n_trip=len({o["trip_id"] for o in outs}),
        ))
        print("  M=%4.1f dB  P_th=%6.1f dBm  中断 %2d 段  累计 %8.1f s  涉及 %2d 个架次"
              % (m, COMM.P_TH, len(outs),
                 sum(o["t1"] - o["t0"] for o in outs),
                 len({o["trip_id"] for o in outs})))

    # ---- 遮挡附加损耗扫描（固定 M = 基准） ----
    COMM.P_TH = base_pth
    CFG.P_TH = base_pth
    for lo in (5.0, 10.0, 15.0, 20.0):
        COMM.L_OBS = lo
        outs = recompute_outages(trips)
        rows.append(dict(
            param="L_obs", value=lo, L_obs=lo, P_th=base_pth,
            n_seg=len(outs), total_s=round(sum(o["t1"] - o["t0"] for o in outs), 1),
            n_trip=len({o["trip_id"] for o in outs}),
        ))
        print("  L_obs=%4.1f dB  中断 %2d 段  累计 %8.1f s  涉及 %2d 个架次"
              % (lo, len(outs), sum(o["t1"] - o["t0"] for o in outs),
                 len({o["trip_id"] for o in outs})))

    # 复原
    COMM.P_TH = base_pth
    CFG.P_TH = base_pth
    COMM.L_OBS = base_lobs
    COMM.lmax.cache_clear()
    COMM.lmax_bidir.cache_clear()

    df = pd.DataFrame(rows)
    df.to_csv(RES / "q3_sensitivity.csv", index=False, encoding="utf-8-sig")
    with open(RES / "q3_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("已写出 results/q3_sensitivity.csv")


if __name__ == "__main__":
    main()
