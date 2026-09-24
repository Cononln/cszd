# -*- coding: utf-8 -*-
"""问题四：评价准则权重的灵敏度分析。

正文用熵权法客观赋权，权重由三项准则（规模指数、资源缺口、组间不均衡）
在方案间的区分度决定。本脚本保持与 q4_partition.py 完全相同的标准化与
TOPSIS 口径，只替换权重向量，用四种赋权方式重算贴进度：

    熵权法（正文口径）  权重由数据区分度决定
    等权                三项准则各 1/3
    两准则              只用规模指数与资源缺口
    单准则              只用资源缺口

考察的稳健性：每个 K 内的最优划分方案在四种赋权下是否一致。
跨 K 比较不依赖权重（直接比原始准则值：缺口 4 件对 7 件、
规模 32 件对 36 件、不均衡 0.692 对 0.994），故权重灵敏度只影响
同一 K 内的方案排序。

运行： .venv/Scripts/python.exe code/q4/q4_weight_sensitivity.py
输出： results/q4_weight_sensitivity.csv / .json
       results/q4_weight_stability.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "q4"))

from q4_partition import entropy_topsis  # noqa: E402

RES = ROOT / "results"
CRIT = ["规模指数", "资源缺口", "组间不均衡"]


def benefit_matrix(M):
    """与 entropy_topsis 相同的极差标准化：统一转为"越大越好"。"""
    X = np.asarray(M, dtype=float)
    Z = np.zeros_like(X)
    for j in range(X.shape[1]):
        lo, hi = X[:, j].min(), X[:, j].max()
        Z[:, j] = 1.0 if hi - lo < 1e-12 else (hi - X[:, j]) / (hi - lo)
    return Z


def topsis_given_w(Z, w):
    """给定权重向量 w 的 TOPSIS 贴近度（Z 已统一为越大越好）。"""
    V = Z * np.asarray(w, dtype=float)
    best, worst = V.max(axis=0), V.min(axis=0)
    dp = np.linalg.norm(V - best, axis=1)
    dn = np.linalg.norm(V - worst, axis=1)
    return dn / np.maximum(dp + dn, 1e-12)


def main():
    df = pd.read_csv(RES / "q4_partition_all.csv")
    rows = []
    for k in (2, 3):
        sub = df[df["k"] == k].reset_index(drop=True)
        M = sub[CRIT].to_numpy(float)
        score_ent, w_ent = entropy_topsis(M, benefit=[False, False, False])
        Z = benefit_matrix(M)
        assert np.allclose(topsis_given_w(Z, w_ent), score_ent, atol=1e-9), \
            "复算口径与 q4_partition.py 不一致"

        schemes = [
            ("熵权法（正文）", w_ent),
            ("等权", np.array([1 / 3, 1 / 3, 1 / 3])),
            ("两准则", np.array([0.5, 0.5, 0.0])),
            ("单准则", np.array([0.0, 1.0, 0.0])),
        ]
        print("K=%d  熵权 w = 规模 %.4f / 缺口 %.4f / 不均衡 %.4f"
              % (k, *w_ent))
        for name, w in schemes:
            s = topsis_given_w(Z, w)
            i = int(np.argmax(s))
            rows.append(dict(
                K=k, 赋权方式=name,
                权重="%.3f/%.3f/%.3f" % tuple(w),
                最优方案=sub.loc[i, "groups"],
                配置规模=int(sub.loc[i, "配置规模"]),
                资源缺口=int(sub.loc[i, "资源缺口"]),
                组间不均衡=round(float(sub.loc[i, "组间不均衡"]), 4),
                规模指数=round(float(sub.loc[i, "规模指数"]), 4),
                得分=round(float(s[i]), 4)))
            print("   %-12s w=%.3f/%.3f/%.3f -> 规模 %2d  缺口 %d  "
                  "不均衡 %.4f  得分 %.4f"
                  % (name, w[0], w[1], w[2], rows[-1]["配置规模"],
                     rows[-1]["资源缺口"], rows[-1]["组间不均衡"],
                     rows[-1]["得分"]))

    out = pd.DataFrame(rows)
    out.to_csv(RES / "q4_weight_sensitivity.csv", index=False,
               encoding="utf-8-sig")

    # ---- 稳健性判定 1：K 内最优方案是否随赋权方式改变 ----
    stable = {}
    for k in (2, 3):
        s = [r["最优方案"] for r in rows if r["K"] == k]
        uniq = sorted(set(s))
        gaps = sorted({r["资源缺口"] for r in rows if r["K"] == k})
        stable[str(k)] = dict(n_schemes=len(s), n_distinct_best=len(uniq),
                              within_k_stable=(len(uniq) == 1),
                              gap_values=gaps,
                              best=uniq)
        print("\nK=%d：4 种赋权下最优方案取值 %d 个（资源缺口 %s）"
              % (k, len(uniq), gaps))

    # ---- 稳健性判定 2：跨 K 的占优关系是否随赋权方式改变 ----
    names = ["规模指数", "资源缺口", "组间不均衡"]
    dom = {}
    for scheme in ["熵权法（正文）", "等权", "两准则", "单准则"]:
        a = [r for r in rows if r["K"] == 2 and r["赋权方式"] == scheme][0]
        b = [r for r in rows if r["K"] == 3 and r["赋权方式"] == scheme][0]
        ok = all(a[c] < b[c] for c in names)
        dom[scheme] = dict(
            K2=[a[c] for c in names], K3=[b[c] for c in names],
            K2_dominates_K3=bool(ok))
        print("   %-12s K=2 %s  vs  K=3 %s  -> K2 全面占优：%s"
              % (scheme, [a[c] for c in names], [b[c] for c in names], ok))
    stable["cross_k"] = dom

    with open(RES / "q4_weight_stability.json", "w", encoding="utf-8") as f:
        json.dump(stable, f, ensure_ascii=False, indent=1)
    print("\n稳健性：", json.dumps(stable, ensure_ascii=False))


if __name__ == "__main__":
    main()
