# -*- coding: utf-8 -*-
"""Q1-3 Step A：正式优化输入审计（真实数据 + Q1-2 容量边界接入）。

只做审计与门禁检查，不做组批、不做机型选择、不做调度、不绘图。
输出：results/q1_3a_audit.json、results/q1_3a_audit_report.md。

门禁（任一失败即非零退出，不进入 Step B）：
* q1_capacity.csv：45 行 / 39 RATED / 6 ENERGY_LIMITED / 0 EMPTY / 全 feasible；
* 货箱/机型/机队/电池/节点数据合法；
* 单箱可运输性 80/80。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.data import (  # noqa: E402
    load_boxes,
    load_nodes,
    load_transport_batteries,
    load_transport_fleet,
    load_transport_types,
    sid_list,
)

PROJ = Path(__file__).resolve().parents[2]
RES = PROJ / "results"
CAP_CSV = RES / "q1_capacity.csv"

FAILURES: list[str] = []


def require(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)


def main() -> int:
    # ---- Q1-2 容量边界门禁：只读，不重算、不硬编码数值 ----
    cap = pd.read_csv(CAP_CSV)
    counts = cap["capacity_status"].value_counts().to_dict()
    require(len(cap) == 45, f"capacity rows != 45 (={len(cap)})")
    require(counts.get("RATED_CAPACITY", 0) == 39, f"RATED != 39 ({counts})")
    require(counts.get("ENERGY_LIMITED", 0) == 6, f"LIMITED != 6 ({counts})")
    require(counts.get("EMPTY_TRIP_INFEASIBLE", 0) == 0, f"EMPTY != 0 ({counts})")
    require(bool(cap["qmax_feasible"].all()), "not all qmax_feasible")
    qmax_map = {(r.gtype, r.sid): float(r.q_max_kg) for r in cap.itertuples()}

    # ---- 真实数据装载 ----
    sids = sid_list()
    boxes = load_boxes()
    types = load_transport_types()
    fleet = load_transport_fleet()
    batteries = load_transport_batteries()
    nodes = load_nodes()

    # ---- 货箱审计 ----
    require(len(boxes) == 80, f"n_boxes != 80 (={len(boxes)})")
    require(bool(boxes["box"].is_unique), "box id not unique")
    require(bool(boxes["sid"].isin(sids).all()), "illegal sid found")
    require(bool((boxes["mass"] > 0).all()), "non-positive mass found")
    require(bool((boxes["vol"] > 0).all()), "non-positive vol found")
    require(bool(boxes["first"].isin([True, False]).all()), "first field illegal")
    first = boxes[boxes["first"]]
    require(bool(first["t_first"].notna().all()), "first box missing t_first")
    require(bool((first["t_first"] > 0).all()), "non-positive t_first found")
    require(bool(boxes["t_exp"].notna().all()), "missing t_exp found")
    require(bool((boxes["t_exp"] > 0).all()), "non-positive t_exp found")
    require(bool(boxes["prio"].notna().all()), "missing prio found")
    require(bool((boxes["prio"] > 0).all()), "non-positive prio found")

    # ---- 机型/机队/电池/节点审计 ----
    tfields = {"Q", "V", "Euse", "rho", "t_prep", "t_box_load",
               "t_hand_base", "t_hand_box", "vc", "v_up", "v_down"}
    require(set(types.keys()) == {"A", "B", "C"}, "gtypes != ABC")
    for g, t in types.items():
        require(tfields.issubset(set(t.keys())), f"type {g} missing fields")
        require(all(pd.notna(t[k]) and t[k] > 0 for k in
                    ["Q", "V", "Euse", "vc", "v_up", "v_down"]), f"type {g} bad params")
        require(all(pd.notna(t[k]) and t[k] >= 0 for k in
                    ["t_prep", "t_box_load", "t_hand_base", "t_hand_box"]),
                f"type {g} bad time params")
        require(0 < t["rho"] < 1, f"type {g} bad rho")
    require(bool(fleet["gtype"].isin(["A", "B", "C"]).all()), "fleet illegal gtype")
    require(bool(fleet["uid"].is_unique), "fleet uid not unique")
    fleet_counts = fleet["gtype"].value_counts().to_dict()
    require(bool((((nodes["id"] == "O01") | nodes["id"].isin(sids))).all())
            and len(nodes) == 16, "nodes != O01+15S")

    # ---- 单箱可运输性 80/80 ----
    infeasible: list[str] = []
    for r in boxes.itertuples():
        ok = any(
            r.mass <= qmax_map[(g, r.sid)] + 1e-9
            and r.vol <= types[g]["V"] + 1e-12
            for g in ("A", "B", "C")
        )
        if not ok:
            infeasible.append(str(r.box))
    require(len(infeasible) == 0, f"infeasible boxes: {infeasible}")

    by_sid = (boxes.groupby("sid")
              .agg(n_boxes=("box", "size"), mass_kg=("mass", "sum"),
                   vol_m3=("vol", "sum")).reset_index())

    audit = {
        "phase": "Q1-3-StepA",
        "scope": "正式输入审计与容量边界门禁；未组批、未调度",
        "capacity_gate": {
            "rows": int(len(cap)), "counts": counts,
            "all_qmax_feasible": bool(cap["qmax_feasible"].all()),
            "pass": len([f for f in FAILURES if "capacity" in f or "RATED" in f
                         or "LIMITED" in f or "EMPTY" in f or "qmax" in f]) == 0,
        },
        "boxes": {
            "n_boxes": int(len(boxes)),
            "total_mass_kg": float(boxes["mass"].sum()),
            "total_volume_m3": float(boxes["vol"].sum()),
            "by_sid": by_sid.to_dict(orient="records"),
            "n_first": int(boxes["first"].sum()),
            "first_mass_kg": float(first["mass"].sum()),
            "first_volume_m3": float(first["vol"].sum()),
            "single_box_feasible": f"{80 - len(infeasible)}/80",
            "infeasible_boxes": infeasible,
        },
        "fleet": {"counts": {k: int(v) for k, v in fleet_counts.items()},
                  "uids": fleet["uid"].tolist()},
        "batteries": batteries,
        "battery_rule_q1": ("Q1 不做共享电池动态充换调度；仅以单架次能量 "
                            "E_trip <= (1-rho)E_use（经 qmax 筛选 + leg_energy 回代双验收）为准"),
        "failures": FAILURES,
        "stepA_pass": len(FAILURES) == 0,
    }
    RES.mkdir(exist_ok=True)
    (RES / "q1_3a_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    L = ["# Q1-3 Step A 审计报告（正式输入，未优化）", "",
         "## 容量边界门禁",
         f"- rows = {len(cap)}（要求 45）",
         f"- RATED = {counts.get('RATED_CAPACITY', 0)}（要求 39）",
         f"- LIMITED = {counts.get('ENERGY_LIMITED', 0)}（要求 6）",
         f"- EMPTY = {counts.get('EMPTY_TRIP_INFEASIBLE', 0)}（要求 0）",
         f"- qmax_feasible 全真：{bool(cap['qmax_feasible'].all())}", "",
         "## 真实货箱",
         f"- 总数 {len(boxes)} / 总质量 {boxes['mass'].sum():.3f} kg / "
         f"总体积 {boxes['vol'].sum():.6f} m^3",
         f"- 首批 {int(boxes['first'].sum())} 箱 / "
         f"{first['mass'].sum():.3f} kg / {first['vol'].sum():.6f} m^3",
         f"- 单箱可运输性：{80 - len(infeasible)}/80", "",
         "## 机队与电池",
         f"- 实体机：{fleet_counts}（共 {len(fleet)} 架）",
         f"- 共享电池：{batteries}",
         f"- 电池规则：{audit['battery_rule_q1']}", "",
         "## 结论",
         f"- StepA_pass = {len(FAILURES) == 0}",
         f"- failures = {FAILURES if FAILURES else '无'}", ""]
    (RES / "q1_3a_audit_report.md").write_text("\n".join(L), encoding="utf-8")
    print(json.dumps({"stepA_pass": len(FAILURES) == 0, "failures": FAILURES,
                      "single_box_feasible": f"{80 - len(infeasible)}/80"},
                     ensure_ascii=False))
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    raise SystemExit(main())
