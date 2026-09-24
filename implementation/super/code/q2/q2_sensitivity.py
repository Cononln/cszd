# -*- coding: utf-8 -*-
"""问题二电池等效充电时间灵敏度分析。

题目给出的等效完全充电时间 T_full 是厂商标称值，实际会随温度、老化与
充电桩状态漂移。本脚本把 T_full 整体缩放 k 倍后重跑完整求解流程
（Stage A 参考解 + 时限感知构造 + ALNS 改进 + 可行性校核），
考察完工期、准时率与架次数对充电速度的敏感性。

运行： python code/q2/q2_sensitivity.py
输出： results/q2_sensitivity.csv, results/q2_sensitivity.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import q2.q2_model as M
import q2.q2_main as Q

RES = ROOT / "results"
BASE_TFULL = dict(M.T_FULL)


def run_scaled(k, iters=15000, time_limit=240.0):
    """把 T_full 缩放 k 倍后跑一遍完整流程，返回关键指标。"""
    M.T_FULL = {g: v * k for g, v in BASE_TFULL.items()}
    Q.T_FULL = M.T_FULL          # q2_main 若从本模块导入则同步
    t0 = time.time()
    best, sched, met = Q.main(iters=iters, time_limit=time_limit)
    dt = time.time() - t0
    return dict(
        scale=k,
        T_full_A=round(M.T_FULL["A"], 1), T_full_B=round(M.T_FULL["B"], 1),
        T_full_C=round(M.T_FULL["C"], 1),
        n_trips=len(best), energy=round(sum(t.energy for t in best), 4),
        makespan=round(met["makespan"], 1),
        on_time_rate=round(met["on_time_rate"], 4),
        late_boxes=met["late_boxes"],
        first_violation=round(met["first_violation"], 1),
        runtime_s=round(dt, 1),
    )


def main(ks=(0.8, 1.0, 1.2), iters=15000, time_limit=240.0):
    # q2_main.main() 会覆写 results/q2_*.csv，先备份基准结果，跑完再复原
    backup = {}
    for p in RES.glob("q2_*.csv"):
        backup[p.name] = p.read_bytes()
    jf = RES / "q2_results.json"
    if jf.exists():
        backup[jf.name] = jf.read_bytes()

    rows = []
    try:
        for k in ks:
            print("=" * 60)
            print("T_full 缩放系数 k = %.2f" % k)
            r = run_scaled(k, iters=iters, time_limit=time_limit)
            rows.append(r)
            print("  架次 %d  能耗 %.3f kWh  完工期 %.0f s  准时率 %.4f  "
                  "超期 %s  首批违约 %.0f s"
                  % (r["n_trips"], r["energy"], r["makespan"], r["on_time_rate"],
                     r["late_boxes"], r["first_violation"]))
    finally:
        M.T_FULL = dict(BASE_TFULL)
        for name, blob in backup.items():
            (RES / name).write_bytes(blob)
        print("已复原 results/ 下的基准结果文件")

    df = pd.DataFrame(rows)
    df.to_csv(RES / "q2_sensitivity.csv", index=False, encoding="utf-8-sig")
    with open(RES / "q2_sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(df.to_string())
    print("已写出 results/q2_sensitivity.csv")


if __name__ == "__main__":
    main()
