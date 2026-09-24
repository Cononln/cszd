# -*- coding: utf-8 -*-
"""Q1-3 Step B：单服务区候选架次生成 + 精确集合划分组批。

模型（主方案只用单服务区架次 O01->Si->O01，使 qmax(g,s) 可直接作能量边界）：
* 质量：sum(m) <= Qeff[g][s] = min(Qg, qmax(g,s))，并防御性检查 sum(m) <= Qg；
* 体积：sum(v) <= Vg（独立约束，不折算）；
* 覆盖：每箱恰好进入一个架次，不拆分、不重复、不遗漏。

方法：
* baseline_ffd(...)：按（首批优先，截止早优先，优先级高优先）排序后 FFD；
* exact_cover(...)：可行子集全枚举（递归剪枝）+ OR-Tools CP-SAT 精确集合划分，
  主目标最少架次，次目标最小质量闲置。规模：单服务区至多 15 箱。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.data import load_boxes, load_transport_types  # noqa: E402

try:
    from ortools.sat.python import cp_model
    HAS_CPSAT = True
except ImportError:
    HAS_CPSAT = False

CAP_CSV = Path(__file__).resolve().parents[2] / "results" / "q1_capacity.csv"
BIG = 10 ** 9  # 主/次目标词典序权重


def load_qeff() -> tuple[dict, dict]:
    """返回 (Qeff[g][s], types)。Qeff = min(Qg, qmax)，唯一来源 q1_capacity.csv。"""
    cap = pd.read_csv(CAP_CSV)
    assert len(cap) == 45 and bool(cap["qmax_feasible"].all())
    types = load_transport_types()
    qeff: dict = {g: {} for g in types}
    for r in cap.itertuples():
        qeff[r.gtype][r.sid] = min(float(types[r.gtype]["Q"]), float(r.q_max_kg))
    return qeff, types


def _order_key(r) -> tuple:
    return (0 if r.first else 1, float(r.t_first if r.first else r.t_exp),
            -float(r.prio), str(r.box))


def baseline_ffd(sid_boxes: pd.DataFrame, gtype: str, qeff: dict,
                 types: dict) -> list[list[str]]:
    """单（sid, 机型）FFD 组批，返回每架次的 box 列表。"""
    sid = str(sid_boxes.iloc[0]["sid"])
    lim_m = qeff[gtype][sid]
    lim_v = float(types[gtype]["V"])
    order = sorted(sid_boxes.itertuples(), key=_order_key)
    bins: list[list] = []
    for r in order:
        placed = False
        for b in bins:
            m = sum(x.mass for x in b) + r.mass
            v = sum(x.vol for x in b) + r.vol
            if m <= lim_m + 1e-9 and v <= lim_v + 1e-12:
                b.append(r)
                placed = True
                break
        if not placed:
            bins.append([r])
    return [[x.box for x in b] for b in bins]


def baseline_choose_type(sid_boxes: pd.DataFrame, qeff: dict,
                         types: dict) -> tuple[str, list[list[str]]]:
    """Baseline 机型选择：取 FFD 架次最少的机型；并列取总任务时间最短者。”"""
    sid = str(sid_boxes.iloc[0]["sid"])
    best = None
    for g in ("A", "B", "C"):
        trips = baseline_ffd(sid_boxes, g, qeff, types)
        t = types[g]
        est = len(trips) * (t["t_prep"] + t["t_hand_base"])
        key = (len(trips), est, g)
        if best is None or key < best[0]:
            best = (key, g, trips)
    return best[1], best[2]


def feasible_subsets(sid_boxes: pd.DataFrame, gtype: str, qeff: dict,
                     types: dict) -> list[list[str]]:
    """递归剪枝枚举全部可行非空子集（质量 + 体积）。"""
    sid = str(sid_boxes.iloc[0]["sid"])
    lim_m = qeff[gtype][sid]
    lim_v = float(types[gtype]["V"])
    rows = list(sid_boxes.itertuples())
    out: list[list[str]] = []
    cur: list = []

    def rec(i: int, m: float, v: float) -> None:
        if cur:
            out.append([x.box for x in cur])
        for j in range(i, len(rows)):
            r = rows[j]
            nm, nv = m + r.mass, v + r.vol
            if nm <= lim_m + 1e-9 and nv <= lim_v + 1e-12:
                cur.append(r)
                rec(j + 1, nm, nv)
                cur.pop()

    rec(0, 0.0, 0.0)
    return out


def exact_cover(sid_boxes: pd.DataFrame, qeff: dict, types: dict,
                time_limit_s: float = 30.0, seed: int = 7,
                type_penalty: dict | None = None) -> list[tuple[str, list[str]]]:
    """单服务区精确集合划分，返回 [(gtype, [boxes])]。

    词典序目标：最少架次 → 最小质量闲置（+ 机型罚项，用于在同架次数内
    调节机型构成；罚项远小于单架次权重，不改变架次最优性）。
    """
    if not HAS_CPSAT:
        raise RuntimeError("OR-Tools CP-SAT not available")
    sid = str(sid_boxes.iloc[0]["sid"])
    boxes = [str(b) for b in sid_boxes["box"]]
    mass = dict(zip(sid_boxes["box"].astype(str), sid_boxes["mass"].astype(float)))
    pen = type_penalty or {}
    cands: list[tuple[str, list[str], int]] = []  # (gtype, boxes, cost)
    for g in ("A", "B", "C"):
        lim_m = qeff[g][sid]
        for s in feasible_subsets(sid_boxes, g, qeff, types):
            m = sum(mass[b] for b in s)
            cands.append((g, s, int(round((lim_m - m) * 1000)) + int(pen.get(g, 0))))
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f"c{i}") for i in range(len(cands))]
    for b in boxes:
        model.Add(sum(x[i] for i, (_, s, _) in enumerate(cands) if b in s) == 1)
    n_trips = sum(x)
    waste = sum(x[i] * cands[i][2] for i in range(len(cands)))
    model.Minimize(n_trips * 10 ** 12 + waste)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 8
    st = solver.Solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT failed for {sid}: {st}")
    return [(cands[i][0], cands[i][1]) for i in range(len(cands))
            if solver.Value(x[i]) > 0]


def cover_pool(sid_boxes: pd.DataFrame, qeff: dict, types: dict,
               max_covers: int = 40) -> list[list[tuple[str, list[str]]]]:
    """同架次数候选覆盖池：基准精确覆盖 + 互补二划分枚举。

    互补二划分：对机型 g 的每个可行子集 S，若其补集对某机型 g2 亦可行，
    则 [(g,S),(g2,补集)] 为一个合法 2 架次覆盖。用于在最少架次数内提供
    分组多样性（含截止时间同质性不同的分法），供坐标下降做调度级选择。
    全程确定性（固定枚举顺序、去重、按闲置排序截断，基准覆盖恒为首个）。
    仅适用于最少架次数 <= 2 的服务区（当前数据全部满足）。
    """
    sid = str(sid_boxes.iloc[0]["sid"])
    boxes = [str(b) for b in sid_boxes["box"]]
    mass = {b: float(m) for b, m in
            zip(sid_boxes["box"].astype(str), sid_boxes["mass"].astype(float))}
    vol = {b: float(v) for b, v in
           zip(sid_boxes["box"].astype(str), sid_boxes["vol"].astype(float))}
    tot_m = sum(mass.values())
    tot_v = sum(vol.values())
    boxset = set(boxes)

    base = exact_cover(sid_boxes, qeff, types)
    covers = [base]
    seen = {tuple(sorted((g, tuple(sorted(p))) for g, p in base))}
    if len(base) > 2:
        return covers
    scored: list[tuple[int, list[tuple[str, list[str]]]]] = []
    for g in ("A", "B", "C"):
        lim_m = qeff[g][sid]
        lim_v = float(types[g]["V"])
        for s in feasible_subsets(sid_boxes, g, qeff, types):
            sset = set(s)
            if not sset or len(sset) == len(boxes):
                continue
            rest = sorted(boxset - sset)
            rm = tot_m - sum(mass[b] for b in s)
            rv = tot_v - sum(vol[b] for b in s)
            for g2 in ("A", "B", "C"):
                if rm <= qeff[g2][sid] + 1e-9 and rv <= float(types[g2]["V"]) + 1e-12:
                    key = tuple(sorted([(g, tuple(sorted(s))), (g2, tuple(rest))],
                                       key=lambda t: (t[0], t[1])))
                    if key not in seen:
                        seen.add(key)
                        m1 = sum(mass[b] for b in s)
                        waste = int(round((lim_m - m1) * 1000
                                          + (qeff[g2][sid] - rm) * 1000))
                        scored.append((waste, [(g, list(s)), (g2, rest)]))
                    break
    scored.sort(key=lambda t: t[0])
    covers += [c for _, c in scored[:max(0, max_covers - 1)]]
    return covers


def binding_of(mass: float, vol: float, lim_m: float, lim_v: float) -> str:
    um, uv = mass / lim_m if lim_m > 0 else 1.0, vol / lim_v if lim_v > 0 else 1.0
    m_full, v_full = um >= 1 - 1e-9, uv >= 1 - 1e-9
    if m_full and v_full:
        return "BOTH_CAPACITY"
    if m_full:
        return "MASS"
    if v_full:
        return "VOLUME"
    return "NONE"
