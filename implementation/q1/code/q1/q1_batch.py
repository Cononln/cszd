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
from common.route import leg_energy, leg_time  # noqa: E402

try:
    from ortools.sat.python import cp_model
    HAS_CPSAT = True
except ImportError:
    HAS_CPSAT = False

CAP_CSV = Path(__file__).resolve().parents[2] / "results" / "q1_capacity.csv"

# CP-SAT 整数缩放（能量 kWh->μkWh，时间 s->ms）
E_SCALE = 10 ** 6
T_SCALE = 10 ** 3
# 第三阶段能量松弛（kWh），数值安全容差
ENERGY_TOL_KWH = 1e-6


def load_qeff() -> tuple[dict, dict]:
    """返回 (Qeff[g][s], types)。Qeff = min(Qg, qmax)，唯一来源 q1_capacity.csv。"""
    cap = pd.read_csv(CAP_CSV, encoding="utf-8-sig")
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
    """Baseline 机型选择：最少架次 → 最小总能耗 → 最小累计作业时间。"""
    sid = str(sid_boxes.iloc[0]["sid"])
    best = None
    for g in ("A", "B", "C"):
        packs = baseline_ffd(sid_boxes, g, qeff, types)
        e = sum(batch_energy_cost(sid, g, p, sid_boxes) for p in packs)
        t = sum(batch_time_cost(sid, g, len(p), types) for p in packs)
        key = (len(packs), round(e, 9), round(t, 9), g)
        if best is None or key < best[0]:
            best = (key, g, packs)
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


def batch_energy_cost(sid: str, gtype: str, pack: list[str],
                      sid_boxes: pd.DataFrame) -> float:
    """候选批次真实能耗：E_out(q)+E_back(0)，冻结 leg_energy。"""
    m = float(sid_boxes.set_index("box").loc[pack, "mass"].sum())
    return float(leg_energy(gtype, "O01", sid, m)
                 + leg_energy(gtype, sid, "O01", 0.0))


def batch_time_cost(sid: str, gtype: str, n: int, types: dict) -> float:
    """候选批次累计作业时间：准备/装载 + 去程 + 交接 + 返程（冻结 leg_time）。"""
    gt = types[gtype]
    return float(gt["t_prep"] + n * gt["t_box_load"] + leg_time(gtype, "O01", sid)
                 + gt["t_hand_base"] + n * gt["t_hand_box"]
                 + leg_time(gtype, sid, "O01"))


def candidate_batches(sid_boxes: pd.DataFrame, qeff: dict,
                      types: dict) -> list[dict]:
    """全部候选批次（分机型可行子集），预计算质量/体积/能量/作业时间。"""
    sid = str(sid_boxes.iloc[0]["sid"])
    mass = {b: float(m) for b, m in
            zip(sid_boxes["box"].astype(str), sid_boxes["mass"].astype(float))}
    out: list[dict] = []
    for g in ("A", "B", "C"):
        lim_m = qeff[g][sid]
        for s in feasible_subsets(sid_boxes, g, qeff, types):
            m = sum(mass[b] for b in s)
            v = sum(float(sid_boxes.set_index("box").loc[b, "vol"]) for b in s)
            out.append({"gtype": g, "boxes": list(s), "mass": m, "vol": v,
                        "energy": batch_energy_cost(sid, g, s, sid_boxes),
                        "optime": batch_time_cost(sid, g, len(s), types)})
    return out


def exact_cover_lex(sid_boxes: pd.DataFrame, qeff: dict, types: dict,
                    time_limit_s: float = 60.0, seed: int = 7) -> dict:
    """单服务区三阶段词典序精确集合划分。

    L1: min 架次 -> N*；L2: 架次=N* 下 min 总能耗 -> E*；
    L3: 架次=N*、能耗<=E*+容差 下 min 累计作业时间。
    返回 {"cover": L3 正式覆盖, "stages": {"L1":.., "L2":.., "L3":..},
    "metrics": {"L1":(N,E,T), ...}}，供 Pareto 权衡分析。
    """
    if not HAS_CPSAT:
        raise RuntimeError("OR-Tools CP-SAT not available")
    sid = str(sid_boxes.iloc[0]["sid"])
    boxes = [str(b) for b in sid_boxes["box"]]
    cands = candidate_batches(sid_boxes, qeff, types)
    e_int = [int(round(c["energy"] * E_SCALE)) for c in cands]
    t_int = [int(round(c["optime"] * T_SCALE)) for c in cands]

    def _solve(extra=(), objective=None):
        model = cp_model.CpModel()
        x = [model.NewBoolVar(f"c{i}") for i in range(len(cands))]
        for b in boxes:
            model.Add(sum(x[i] for i, c in enumerate(cands) if b in c["boxes"]) == 1)
        for con in extra:
            model.Add(con(x))
        model.Minimize(objective(x))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        solver.parameters.random_seed = seed
        solver.parameters.num_search_workers = 8
        st = solver.Solve(model)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"CP-SAT failed for {sid}: {st}")
        return [i for i in range(len(cands)) if solver.Value(x[i]) > 0], st

    n_var = lambda x: sum(x)
    e_var = lambda x: sum(x[i] * e_int[i] for i in range(len(cands)))
    t_var = lambda x: sum(x[i] * t_int[i] for i in range(len(cands)))
    waste = [int(round((qeff[c["gtype"]][sid] - c["mass"]) * 1000)) for c in cands]
    w_var = lambda x: sum(x[i] * waste[i] for i in range(len(cands)))

    sel1, _ = _solve(objective=lambda x: n_var(x) * 10 ** 9 + w_var(x))
    n_star = len(sel1)
    sel2, _ = _solve(extra=(lambda x: n_var(x) == n_star,),
                      objective=lambda x: e_var(x) * 10 ** 3 + w_var(x))
    e_star = sum(e_int[i] for i in sel2)
    eps = max(1, int(round(ENERGY_TOL_KWH * E_SCALE)))
    sel3, _ = _solve(
        extra=(lambda x: n_var(x) == n_star, lambda x: e_var(x) <= e_star + eps),
        objective=lambda x: t_var(x) * 10 ** 3 + w_var(x))

    def _cover(sel):
        return [(cands[i]["gtype"], cands[i]["boxes"]) for i in sel]

    def _met(sel):
        n = len(sel)
        e = sum(cands[i]["energy"] for i in sel)
        t = sum(cands[i]["optime"] for i in sel)
        return (n, e, t)

    return {"cover": _cover(sel3),
            "stages": {"L1": _cover(sel1), "L2": _cover(sel2), "L3": _cover(sel3)},
            "metrics": {"L1": _met(sel1), "L2": _met(sel2), "L3": _met(sel3)}}


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
