# -*- coding: utf-8 -*-
"""
问题一第二种思路：局部Pareto前沿 + 全局Minkowski合并 + Chebyshev妥协。

本程序独立写入 p1-2/outputs 和 p1-2/figures，不修改项目根目录中的任何
q1_21.py、q1_22.py、q1_23.py或原有结果文件。

算法流程：
  1. 复用 q1_2_common.py 的候选架次生成口径，保证与三个原有程序可比；
  2. 对每个服务区分别用集合划分MILP生成局部非支配解；
  3. 通过Minkowski和逐个合并15个服务区的局部Pareto前沿；
  4. 对全局Pareto前沿采用等权Chebyshev距离选取均衡方案。
"""

from __future__ import annotations

import sys
from pathlib import Path
from itertools import product

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "outputs"
FIG = HERE / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

# 只读取原有公共数据模块，不执行其主程序，也不写入根目录。
sys.path.insert(0, str(ROOT))
from q1_2_common import load_base_data, enumerate_candidates  # noqa: E402


EPS = 1e-8
TIME_LIMIT = 30.0
# 默认先合并三个单目标精确解，保证程序运行稳定；如需更密集的局部
# Pareto前沿，可将该值改为1、2或3，再重新运行。
MAX_EXTRA_N = 0
MAX_GLOBAL_FRONT = 500


def as_tuple(x):
    if isinstance(x, tuple):
        return x
    if isinstance(x, list):
        return tuple(x)
    if isinstance(x, str):
        return tuple(x.split("|"))
    return tuple(x)


def build_local_matrix(csub: pd.DataFrame, bsub: pd.DataFrame):
    box_ids = list(bsub["货箱编号"])
    pos = {b: i for i, b in enumerate(box_ids)}
    A = lil_matrix((len(box_ids), len(csub)), dtype=float)
    for j, items in enumerate(csub["货箱列表"]):
        for b in as_tuple(items):
            A[pos[b], j] = 1.0
    return A.tocsr(), box_ids


def solve_local(csub: pd.DataFrame, bsub: pd.DataFrame, objective: str,
                n_target: int | None = None):
    """求解一个服务区的集合划分子问题。"""
    A, box_ids = build_local_matrix(csub, bsub)
    constraints = [LinearConstraint(A, np.ones(len(box_ids)), np.ones(len(box_ids)))]
    if n_target is not None:
        card = np.ones((1, len(csub)))
        constraints.append(LinearConstraint(card, [n_target], [n_target]))

    if objective == "N":
        cost = np.ones(len(csub))
    elif objective == "E":
        cost = csub["E_batch_kWh"].to_numpy(float)
    elif objective == "T":
        cost = csub["T_batch_s"].to_numpy(float)
    else:
        raise ValueError(objective)

    res = milp(
        c=cost,
        integrality=np.ones(len(csub)),
        bounds=Bounds(0, 1),
        constraints=constraints,
        options={"time_limit": TIME_LIMIT, "mip_rel_gap": 1e-8},
    )
    # S001的候选列较多，HiGHS可能在时间上限前已有可行整数解。
    # 只要返回了x，就保留该可行解参与Pareto合并；最终会重新复核覆盖关系。
    if not res.success and res.x is None:
        raise RuntimeError(f"服务区{bsub['服务区编号'].iloc[0]}目标{objective}求解失败：{res.message}")
    idx = np.flatnonzero(np.asarray(res.x) > 0.5)
    if len(idx) == 0:
        raise RuntimeError("MILP没有返回非空覆盖方案")
    return idx


def metrics(csub: pd.DataFrame, idx: np.ndarray):
    selected = csub.iloc[idx]
    return {
        "N": int(len(selected)),
        "E_total": float(selected["E_batch_kWh"].sum()),
        "T_total": float(selected["T_batch_s"].sum()),
        "candidate_ids": [int(x) for x in selected["候选编号"].tolist()],
    }


def nondominated(points):
    """对字典列表按(N,E,T)做最小化非支配过滤。"""
    # 同一目标点只保留第一份方案，避免合并时出现大量重复组合。
    unique = {}
    for p in points:
        key = (int(p["N"]), round(float(p["E_total"]), 9), round(float(p["T_total"]), 6))
        unique.setdefault(key, p)
    arr = list(unique.values())
    keep = []
    for i, a in enumerate(arr):
        dominated = False
        for j, b in enumerate(arr):
            if i == j:
                continue
            no_worse = (b["N"] <= a["N"] + EPS and
                        b["E_total"] <= a["E_total"] + EPS and
                        b["T_total"] <= a["T_total"] + EPS)
            strictly = (b["N"] < a["N"] - EPS or
                        b["E_total"] < a["E_total"] - EPS or
                        b["T_total"] < a["T_total"] - EPS)
            if no_worse and strictly:
                dominated = True
                break
        if not dominated:
            keep.append(a)
    keep.sort(key=lambda p: (p["N"], p["E_total"], p["T_total"]))
    return keep


def local_pareto(candidates: pd.DataFrame, boxes: pd.DataFrame):
    local_all = []
    service_ids = sorted(boxes["服务区编号"].unique())
    for service in service_ids:
        bsub = boxes[boxes["服务区编号"] == service].copy()
        csub = candidates[candidates["服务区编号"] == service].reset_index(drop=True)
        solutions = []

        # 三个单目标解。
        for obj in ["N", "E", "T"]:
            idx = solve_local(csub, bsub, obj)
            m = metrics(csub, idx)
            m["service"] = service
            solutions.append(m)

        n_min = min(x["N"] for x in solutions)
        # 固定架次数的epsilon约束扫描，捕捉架次增加后能耗/时间下降的方案。
        if MAX_EXTRA_N > 0:
            for n_target in range(n_min, n_min + MAX_EXTRA_N + 1):
                for obj in ["E", "T"]:
                    try:
                        idx = solve_local(csub, bsub, obj, n_target=n_target)
                    except RuntimeError:
                        continue
                    m = metrics(csub, idx)
                    m["service"] = service
                    solutions.append(m)

        front = nondominated(solutions)
        for k, p in enumerate(front, start=1):
            p["local_id"] = k
            p["candidate_ids_text"] = "|".join(map(str, p["candidate_ids"]))
            local_all.append(p.copy())
        print(f"{service}: 候选{len(csub)}列，局部Pareto {len(front)}个")
    return pd.DataFrame(local_all)


def merge_global(local_df: pd.DataFrame):
    front = [{"N": 0, "E_total": 0.0, "T_total": 0.0, "parts": []}]
    for service in sorted(local_df["service"].unique()):
        rows = local_df[local_df["service"] == service].to_dict("records")
        combined = []
        for a, b in product(front, rows):
            combined.append({
                "N": int(a["N"] + b["N"]),
                "E_total": float(a["E_total"] + b["E_total"]),
                "T_total": float(a["T_total"] + b["T_total"]),
                "parts": a["parts"] + [{"service": service, "local_id": int(b["local_id"]),
                                          "candidate_ids": list(map(int, b["candidate_ids"]))}],
            })
        front = nondominated(combined)
        # 正常情况下局部前沿很小；此上限只是防止异常数据造成组合爆炸。
        if len(front) > MAX_GLOBAL_FRONT:
            front = sorted(front, key=lambda x: (x["N"], x["E_total"], x["T_total"]))[:MAX_GLOBAL_FRONT]
        print(f"合并到{service}后，全局前沿{len(front)}个")
    return front


def choose_chebyshev(front):
    ideal = {k: min(p[k] for p in front) for k in ["N", "E_total", "T_total"]}
    nadir = {k: max(p[k] for p in front) for k in ["N", "E_total", "T_total"]}

    def deviation(p):
        vals = []
        for k in ["N", "E_total", "T_total"]:
            den = nadir[k] - ideal[k]
            vals.append(0.0 if den <= EPS else (p[k] - ideal[k]) / den / 3.0)
        return max(vals)

    chosen = min(front, key=lambda p: (deviation(p), p["N"], p["E_total"], p["T_total"]))
    return chosen, ideal, nadir, deviation


def add_batch_names(selected: pd.DataFrame):
    selected = selected.sort_values(["服务区编号", "候选编号"]).reset_index(drop=True).copy()
    counters = {}
    names = []
    for _, r in selected.iterrows():
        s = r["服务区编号"]
        counters[s] = counters.get(s, 0) + 1
        names.append(f"{s}-B{counters[s]:02d}")
    selected.insert(0, "批次编号", names)
    return selected


def expand_assignment(selected):
    rows = []
    for _, r in selected.iterrows():
        for bid in as_tuple(r["货箱列表"]):
            rows.append({"货箱编号": bid, "服务区编号": r["服务区编号"],
                         "批次编号": r["批次编号"], "机型编号": r["机型编号"]})
    return pd.DataFrame(rows)


def save_figures(local_df, global_df, final_batches):
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 130
    plt.rcParams["savefig.dpi"] = 220

    sizes = local_df.groupby("service").size()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(sizes.index, sizes.values, color="#2a78d6")
    ax.set_ylabel("局部非支配方案数"); ax.set_title("p1-2：各服务区局部Pareto前沿规模")
    ax.tick_params(axis="x", rotation=45); ax.grid(axis="y", alpha=.25)
    fig.tight_layout(); fig.savefig(FIG / "p1-2_01_局部Pareto规模.png", bbox_inches="tight"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5.6))
    sc = ax.scatter(global_df["总能耗E_kWh"], global_df["累计时间T_s"] / 3600,
                    c=global_df["架次数N"], cmap="viridis", s=75, edgecolor="black", linewidth=.4)
    for _, r in global_df.iterrows():
        ax.annotate(str(int(r["架次数N"])), (r["总能耗E_kWh"], r["累计时间T_s"] / 3600), xytext=(4, 4), textcoords="offset points", fontsize=8)
    fig.colorbar(sc, ax=ax, label="架次数N")
    ax.set_xlabel("总能耗（kWh）"); ax.set_ylabel("累计作业时间（h）")
    ax.set_title("p1-2：全局Pareto前沿")
    ax.grid(alpha=.25); fig.tight_layout(); fig.savefig(FIG / "p1-2_02_全局Pareto前沿.png", bbox_inches="tight"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    vals = final_batches.groupby("服务区编号").size()
    ax.bar(vals.index, vals.values, color="#1baf7a")
    ax.set_ylabel("最终方案架次数"); ax.set_title("p1-2：Chebyshev均衡方案的服务区架次分布")
    ax.tick_params(axis="x", rotation=45); ax.grid(axis="y", alpha=.25)
    fig.tight_layout(); fig.savefig(FIG / "p1-2_03_最终方案架次分布.png", bbox_inches="tight"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    z = global_df["Chebyshev偏离度"]
    ax.bar(np.arange(len(z)), z, color="#eb6834")
    ax.set_xlabel("全局Pareto方案编号"); ax.set_ylabel("最大归一化偏离度")
    ax.set_title("p1-2：Pareto方案到理想点的Chebyshev偏离度")
    ax.grid(axis="y", alpha=.25); fig.tight_layout()
    fig.savefig(FIG / "p1-2_04_Chebyshev偏离度.png", bbox_inches="tight"); plt.close(fig)


def main():
    boxes, specs, qmax_lookup, geo_table = load_base_data()
    candidates = enumerate_candidates(boxes, specs, geo_table, qmax_lookup)
    candidates.to_csv(OUT / "p1-2_可行组批候选.csv", index=False, encoding="utf-8-sig")
    print(f"候选架次总数：{len(candidates)}")

    local = local_pareto(candidates, boxes)
    local.to_csv(OUT / "p1-2_各服务区局部Pareto.csv", index=False, encoding="utf-8-sig")

    front = merge_global(local)
    chosen, ideal, nadir, dev = choose_chebyshev(front)
    global_rows = []
    for i, p in enumerate(front, start=1):
        global_rows.append({"全局方案编号": i, "架次数N": p["N"], "总能耗E_kWh": p["E_total"],
                            "累计时间T_s": p["T_total"], "Chebyshev偏离度": dev(p),
                            "局部方案组合": ";".join(f"{q['service']}:{q['local_id']}" for q in p["parts"]),
                            "候选编号列表": "|".join(map(str, [x for q in p["parts"] for x in q["candidate_ids"]]))})
    global_df = pd.DataFrame(global_rows)
    global_df.to_csv(OUT / "p1-2_全局Pareto前沿.csv", index=False, encoding="utf-8-sig")

    chosen_ids = [x for q in chosen["parts"] for x in q["candidate_ids"]]
    final_batches = add_batch_names(candidates[candidates["候选编号"].isin(chosen_ids)])
    final_batches.to_csv(OUT / "p1-2_最终Chebyshev组批方案.csv", index=False, encoding="utf-8-sig")
    assignment = expand_assignment(final_batches)
    assignment.to_csv(OUT / "p1-2_逐箱货箱分配.csv", index=False, encoding="utf-8-sig")

    with open(OUT / "p1-2_运行摘要.txt", "w", encoding="utf-8") as f:
        f.write("问题一第二种思路：局部Pareto + Minkowski合并 + Chebyshev妥协\n")
        f.write("=" * 60 + "\n")
        f.write(f"候选架次总数：{len(candidates)}\n")
        f.write(f"局部Pareto方案总数：{len(local)}\n")
        f.write(f"全局Pareto方案数：{len(front)}\n")
        f.write(f"理想点：N={ideal['N']}, E={ideal['E_total']:.6f} kWh, T={ideal['T_total']:.3f} s\n")
        f.write(f"nadir点：N={nadir['N']}, E={nadir['E_total']:.6f} kWh, T={nadir['T_total']:.3f} s\n")
        f.write(f"最终方案：N={chosen['N']}, E={chosen['E_total']:.6f} kWh, T={chosen['T_total']:.3f} s\n")
        f.write(f"最终方案Chebyshev偏离度：{dev(chosen):.6f}\n")
        f.write(f"货箱覆盖数：{len(assignment)}，去重货箱数：{assignment['货箱编号'].nunique()}\n")
        f.write("局部MILP采用架次数扫描的epsilon约束生成Pareto候选；全局合并后再做非支配过滤。\n")

    save_figures(local, global_df, final_batches)
    print("p1-2完成")
    print(f"最终方案：N={chosen['N']}, E={chosen['E_total']:.3f} kWh, T={chosen['T_total']:.1f} s")
    print("结果目录：", OUT)
    print("图形目录：", FIG)


if __name__ == "__main__":
    main()
