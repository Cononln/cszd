# -*- coding: utf-8 -*-
"""问题三：通信参数对中继机队规模需求的灵敏度分析。

q3_sensitivity.py 只重算"中断段数与中断时长"，回答的是需求侧变化；
本脚本进一步把需求侧变化灌进完整的集合覆盖求解流程（候选点枚举 -> 覆盖矩阵
-> 列池生成 -> 支配剪枝 -> CP-SAT 精确覆盖 + 中继无人机无重叠指派），
逐步增加中继无人机架数直至"零未覆盖"，从而给出**满足连续通信所需的最少
中继无人机数量**随通信参数的变化。这正是问题四资源缺口分析的直接依据。

扫描三种参数组合：
    基准        M = 8 dB,  L_obs = 10 dB
    收紧衰落裕量 M = 12 dB, L_obs = 10 dB
    加大遮挡损耗 M = 8 dB,  L_obs = 15 dB

运行： python code/q3/q3_fleet_sensitivity.py
输出： results/q3_fleet_sensitivity.csv, results/q3_fleet_sensitivity.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import common.comm as COMM
import common.config as CFG
import q3.q3_solve as Q

RES = ROOT / "results"
BASE_PTH = CFG.P_TH
BASE_LOBS = COMM.L_OBS


def apply_params(m, l_obs):
    """按给定的衰落裕量与遮挡附加损耗重设通信口径，并清空相关缓存。"""
    COMM.P_TH = CFG.P_SENS + m
    CFG.P_TH = COMM.P_TH
    COMM.L_OBS = l_obs
    COMM.lmax.cache_clear()
    COMM.lmax_bidir.cache_clear()


def restore_params():
    COMM.P_TH = BASE_PTH
    CFG.P_TH = BASE_PTH
    COMM.L_OBS = BASE_LOBS
    COMM.lmax.cache_clear()
    COMM.lmax_bidir.cache_clear()


def build_drones(n):
    """现有中继机队 + 缺口补齐的虚拟中继机编号，用于机队规模试探。"""
    dr = list(Q.REL_FLEET["rid"])
    i = len(dr) + 1
    while len(dr) < n:
        dr.append("R%02d" % i)
        i += 1
    return dr[:n]


def min_fleet(props, n_out, max_n=6, tl=180.0, hint=None):
    """逐步增加中继无人机架数，返回首个实现零未覆盖的机队规模与方案。

    判据采用与 q3_solve 相同的两阶段口径：第一阶段只最小化未覆盖区间数，
    若该值降到 0 则说明该机队规模足以实现全覆盖。若求解器在时限内只给出
    UNKNOWN，则如实记录状态而不是当作"不可行"——二者含义不同。
    """
    trail = []
    for n in range(2, max_n + 1):
        t = time.time()
        sel, unc, st = Q.milp_set_cover(props, n_out, build_drones(n),
                                        time_limit=tl, hint_cols=hint)
        ok = (sel is not None) and (len(unc) == 0)
        trail.append(dict(n_drones=n, status=st, feasible=bool(ok),
                          n_uncovered=(len(unc) if sel is not None else None),
                          runtime_s=round(time.time() - t, 1)))
        if sel is None:
            print("    中继机 %d 架 -> 求解失败（%s，%.0fs）" % (n, st, time.time() - t))
            continue
        print("    中继机 %d 架 -> 未覆盖 %d 个，架次 %d（%s，%.0fs）"
              % (n, len(unc), len(sel), st, time.time() - t))
        if ok:
            return n, sel, unc, st, trail
    return None, None, None, "NO_FULL_COVER", trail


def run_case(name, m, l_obs, max_n=6):
    """一个通信参数组合下的完整需求——覆盖求解。"""
    apply_params(m, l_obs)
    t0 = time.time()
    trips, _ = Q.load_q2_trips()

    timelines = Q.build_timelines(trips)
    outages = []
    for tl_ in timelines:
        for o in Q.outage_intervals(tl_):
            o["trip_id"] = tl_["trip_id"]
            outages.append(o)
    total_s = sum(o["t1"] - o["t0"] for o in outages)

    cand = Q.hover_candidates()
    n_back = int(cand["backhaul_ok"].sum())
    cover = Q.coverage_matrix(cand, timelines, outages)
    props = Q.gen_proposals(cand, outages, cover)

    print("  [%s] P_th=%.0f dBm L_obs=%.0f dB | 中断 %d 段 / %.0f s | "
          "回传可用候选点 %d | 候选列 %d"
          % (name, COMM.P_TH, COMM.L_OBS, len(outages), total_s, n_back, len(props)))

    if not props:
        return dict(case=name, M=m, L_obs=l_obs, P_th=COMM.P_TH,
                    n_outage=len(outages), outage_s=round(total_s, 1),
                    n_backhaul_ok=n_back, n_props=0,
                    min_drones=None, n_relay_trips=None,
                    relay_energy=None, status="EMPTY_POOL",
                    runtime_s=round(time.time() - t0, 1))

    # 贪心解作为 CP-SAT 的可行基，加快"零未覆盖"的判定
    idx_g, _ = Q.greedy_cover(props, len(outages))
    n, sel, unc, st, trail = min_fleet(props, len(outages), max_n=max_n, hint=idx_g)
    unc_s = (sum(outages[j]["t1"] - outages[j]["t0"] for j in unc)
             if unc else 0.0)
    rec = dict(case=name, M=m, L_obs=l_obs, P_th=COMM.P_TH,
               n_outage=len(outages), outage_s=round(total_s, 1),
               n_backhaul_ok=n_back, n_props=len(props),
               min_drones=n, n_relay_trips=(len(sel) if sel else None),
               relay_energy=(round(sum(p["e_total"] for p in sel), 4) if sel else None),
               n_uncovered=(len(unc) if unc is not None else None),
               uncovered_s=round(unc_s, 1),
               status=st, trail=trail, runtime_s=round(time.time() - t0, 1))
    print("  [%s] => 零未覆盖所需中继无人机：%s 架" % (name, n))
    return rec


def freeze_q2_schedule():
    """把问题二的运输方案冻结到临时目录，避免被其他脚本的并发写入污染。

    load_q2_trips() 从 Q.RES/q2_transport_trips.csv 读取运输架次；若此时另有
    脚本（如 q2_sensitivity.py）正在覆写 results/，本脚本会误读到别的方案。
    这里先把该文件复制到独立目录，再把 Q.RES 指向该目录。
    """
    import shutil
    import tempfile
    src = RES / "q2_transport_trips.csv"
    d = Path(tempfile.mkdtemp(prefix="q3_fleet_"))
    shutil.copyfile(src, d / "q2_transport_trips.csv")
    Q.RES = d
    print("已冻结问题二运输方案：%s" % src)


def main():
    Q.precompute_all_legs()
    freeze_q2_schedule()
    cases = [("基准", 8.0, 10.0), ("衰落裕量收紧", 12.0, 10.0),
             ("遮挡损耗加大", 8.0, 15.0)]
    rows = []
    try:
        for nm, m, lo in cases:
            rows.append(run_case(nm, m, lo))
    finally:
        restore_params()
        print("已复原通信参数基准值")

    df = pd.DataFrame(rows).drop(columns=["trail"])
    df.to_csv(RES / "q3_fleet_sensitivity.csv", index=False, encoding="utf-8-sig")
    with open(RES / "q3_fleet_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(df.to_string())
    print("已写出 results/q3_fleet_sensitivity.csv")


if __name__ == "__main__":
    main()
