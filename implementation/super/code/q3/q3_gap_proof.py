# -*- coding: utf-8 -*-
"""问题三：判定"2 架中继无人机是否足以实现连续通信"。

q3_solve.py 的机队规模分析在**列池截断**（6000 列）的模型上得到
"2 架时仍有 2 段未覆盖"，这只是一个上界。q3_fleet_sensitivity.py 改用
**完整列池**（9854 列）后，2 架时能找到只剩 1 段未覆盖的方案，原结论
因此不再可靠。

要断言"存在 1 架中继机的配备缺口"，必须证明 2 架**不可能**做到零未覆盖。
本脚本用 milp_set_cover 的 require_full 分支把问题转化为纯可行性判定：
所有 slack 变量强制为 0，要求覆盖全部中断区间，且**不做任何列池截断**。

    INFEASIBLE -> 2 架不可行，"缺口 1 架"得到证明
    FEASIBLE   -> 2 架可行，论文的缺口结论必须改写
    UNKNOWN    -> 限时内未判定，论文只能报告"至多 1 段未覆盖"这一上界

运行： .venv/Scripts/python.exe code/q3/q3_gap_proof.py [时限秒]
输出： results/q3_gap_proof.json
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import q3.q3_solve as Q  # noqa: E402

RES = ROOT / "results"


def freeze_q2_schedule():
    """冻结问题二运输方案，避免并发脚本覆写 results/ 造成误读。"""
    src = RES / "q2_transport_trips.csv"
    d = Path(tempfile.mkdtemp(prefix="q3_proof_"))
    shutil.copyfile(src, d / "q2_transport_trips.csv")
    Q.RES = d
    print("已冻结问题二运输方案：%s" % src)


def build_drones(n):
    dr = list(Q.REL_FLEET["rid"])
    i = len(dr) + 1
    while len(dr) < n:
        dr.append("R%02d" % i)
        i += 1
    return dr[:n]


def main():
    time_limit = float(sys.argv[1]) if len(sys.argv) > 1 else 900.0
    freeze_q2_schedule()
    Q.precompute_all_legs()

    trips, _ = Q.load_q2_trips()
    timelines = Q.build_timelines(trips)
    outages = []
    for tl in timelines:
        for o in Q.outage_intervals(tl):
            o["trip_id"] = tl["trip_id"]
            outages.append(o)
    n_out = len(outages)

    cand = Q.hover_candidates()
    cover = Q.coverage_matrix(cand, timelines, outages)
    props = Q.gen_proposals(cand, outages, cover)      # 完整列池，不截断
    print("中断区间 %d 个，悬停候选点 %d 个，完整列池 %d 条"
          % (n_out, len(cand), len(props)))

    idx_g, unc_g = Q.greedy_cover(props, n_out)
    print("贪心参考：中继架次 %d 个，未覆盖 %d 段" % (len(idx_g), len(unc_g)))

    out = {"n_outage": n_out, "n_candidates": len(cand), "n_cols": len(props),
           "greedy_trips": len(idx_g), "greedy_uncovered": len(unc_g),
           "time_limit_s": time_limit, "cases": []}

    for n in (2, 3):
        drones = build_drones(n)
        t = time.time()
        sel, unc, st = Q.milp_set_cover(props, n_out, drones,
                                        time_limit=time_limit,
                                        hint_cols=idx_g, require_full=True)
        el = round(time.time() - t, 1)
        ok = sel is not None
        rec = dict(n_drones=n, status=st, full_cover_possible=bool(ok),
                   n_relay_trips=(len(sel) if ok else None),
                   relay_energy=(round(sum(p["e_total"] for p in sel), 4)
                                 if ok else None),
                   runtime_s=el)
        out["cases"].append(rec)
        print("  %d 架 -> %-10s | 零未覆盖%s（%.0fs）"
              % (n, st, "可达" if ok else "不可达", el))

    c2 = out["cases"][0]
    if c2["status"] == "INFEASIBLE":
        out["conclusion"] = ("已证明：2 架中继无人机无法实现连续通信；"
                             "全覆盖所需最少中继机数为 3 架，缺口 1 架成立。")
    elif c2["full_cover_possible"]:
        out["conclusion"] = ("2 架即可实现零未覆盖，论文中“缺口 1 架”的"
                             "结论必须改写。")
    else:
        out["conclusion"] = ("限时内未能判定 2 架是否可行；只能报告"
                             "“2 架时至少 1 段未覆盖”这一上界。")
    print("\n" + out["conclusion"])

    with open(RES / "q3_gap_proof.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("已写出 results/q3_gap_proof.json")


if __name__ == "__main__":
    main()
