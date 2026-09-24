# -*- coding: utf-8 -*-
"""Phase Q1-3 预审：真实输入数据审计 + q1_capacity 接口状态审计。

允许运行。本脚本只做描述统计与接口状态检查：
* 货箱/机型/服务区/首批字段审计；
* q1_capacity.csv 是否存在、结构是否合法；
* 只要 Q1-2 未被宣布验收，正式求解一律 READY=False。

不生成任何正式组批、机型选择或路线结果；不绘图。
输出：results/q1_3_precheck.json、results/q1_3_precheck_report.md。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # code/
sys.path.insert(0, str(Path(__file__).resolve().parent))       # code/q1/

from common.data import load_boxes, load_transport_types, sid_list  # noqa: E402

import q1_batching as qb  # noqa: E402

PROJ = Path(__file__).resolve().parents[2]
RES = PROJ / "results"


def audit_boxes(df: pd.DataFrame, sids: list[str]) -> dict:
    checks = {
        "n_boxes_is_80": len(df) == 80,
        "box_id_unique": bool(df["box"].is_unique),
        "sid_legal": bool(df["sid"].isin(sids).all()),
        "mass_positive": bool((df["mass"] > 0).all()),
        "vol_positive": bool((df["vol"] > 0).all()),
        "first_field_bool": bool(df["first"].isin([True, False]).all()),
    }
    by_sid = (
        df.groupby("sid")
        .agg(n_boxes=("box", "size"), mass_kg=("mass", "sum"), vol_m3=("vol", "sum"))
        .reset_index()
    )
    first_info = qb.check_first_batch_fields(df)
    stats = {
        "n_boxes": int(len(df)),
        "n_sids_covered": int(df["sid"].nunique()),
        "total_mass_kg": float(df["mass"].sum()),
        "total_volume_m3": float(df["vol"].sum()),
        "max_single_mass_kg": float(df["mass"].max()),
        "max_single_vol_m3": float(df["vol"].max()),
        "by_sid": by_sid.to_dict(orient="records"),
        "first": first_info,
    }
    checks["all_pass"] = bool(all(checks.values()))
    return {"checks": checks, "stats": stats}


def audit_types(types: dict) -> dict:
    required = {"Q", "V", "Euse", "rho", "t_prep", "t_box_load",
                "t_hand_base", "t_hand_box", "vc"}
    checks = {
        "n_types_is_3": set(types.keys()) == {"A", "B", "C"},
        "fields_present": all(required.issubset(set(t.keys())) for t in types.values()),
        "Q_positive": all(t["Q"] > 0 for t in types.values()),
        "V_positive": all(t["V"] > 0 for t in types.values()),
    }
    checks["all_pass"] = bool(all(checks.values()))
    summary = {g: {"Q": t["Q"], "V": t["V"]} for g, t in types.items()}
    return {"checks": checks, "summary": summary}


def main() -> int:
    sids = sid_list()
    boxes = load_boxes()
    types = load_transport_types()

    box_audit = audit_boxes(boxes, sids)
    type_audit = audit_types(types)

    cap_status, cap_df = qb.load_q1_capacity()
    if cap_df is None:
        cap_struct = {"all_structural_pass": False, "note": "file_not_found"}
        cap_counts = {}
    else:
        struct = qb.validate_capacity_table(cap_df)
        cap_struct = struct
        cap_counts = {
            "n_rows": int(len(cap_df)),
            "by_status": cap_df["capacity_status"].value_counts().to_dict()
            if "capacity_status" in cap_df.columns else {},
        }

    # 骨架阶段：只要 Q1_2_APPROVED 门为 False，正式求解一律未就绪。
    ready = bool(
        qb.Q1_2_APPROVED
        and box_audit["checks"]["all_pass"]
        and type_audit["checks"]["all_pass"]
        and cap_struct.get("all_structural_pass", False)
    )
    reason = (
        "WAITING_FOR_Q1_2"
        if cap_status == qb.CAPACITY_STATUS_WAITING
        else "Q1_2_RESULT_AVAILABLE_BUT_NOT_YET_APPROVED"
    ) if not ready else "READY"

    precheck = {
        "phase": "Q1-3-PRECHECK",
        "scope": "真实输入审计与容量接口状态；未执行正式组批与优化",
        "boxes": box_audit,
        "transport_types": type_audit,
        "capacity_interface": {
            "path": str(qb.capacity_table_path()),
            "status": cap_status,
            "structural": cap_struct,
            "counts": cap_counts,
            "approved_gate": bool(qb.Q1_2_APPROVED),
        },
        "formal_solve_ready": ready,
        "formal_solve_blocker": reason,
    }
    RES.mkdir(exist_ok=True)
    (RES / "q1_3_precheck.json").write_text(
        json.dumps(precheck, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    s = box_audit["stats"]
    lines = [
        "# Q1-3 预审报告（骨架阶段，非正式求解）",
        "",
        "## 真实货箱描述统计",
        "",
        f"- 货箱总数：{s['n_boxes']}",
        f"- 覆盖服务区：{s['n_sids_covered']}",
        f"- 总质量：{s['total_mass_kg']:.3f} kg",
        f"- 总体积：{s['total_volume_m3']:.6f} m^3",
        f"- 最大单箱质量：{s['max_single_mass_kg']:.3f} kg",
        f"- 最大单箱体积：{s['max_single_vol_m3']:.6f} m^3",
        f"- 首批货箱数：{s['first']['n_first_boxes']}",
        f"- 首批总质量：{s['first']['first_mass_kg']:.3f} kg",
        f"- 首批总体积：{s['first']['first_volume_m3']:.6f} m^3",
        f"- 首批截止时间齐全：{s['first']['all_first_have_deadline']}",
        "",
        "## 各服务区需求",
        "",
        "| sid | n_boxes | mass_kg | vol_m3 |",
        "| --- | --- | --- | --- |",
    ]
    for r in s["by_sid"]:
        lines.append(
            f"| {r['sid']} | {int(r['n_boxes'])} | {r['mass_kg']:.3f} | {r['vol_m3']:.6f} |"
        )
    lines += [
        "",
        "## 机型参数",
        "",
        f"- 机型集合正确（A/B/C）：{type_audit['checks']['n_types_is_3']}",
        f"- 字段齐全：{type_audit['checks']['fields_present']}",
        "",
        "## q1_capacity 接口状态",
        "",
        f"- 状态：{cap_status}",
        f"- 结构校验通过：{cap_struct.get('all_structural_pass', False)}",
        f"- 验收门（Q1_2_APPROVED）：{bool(qb.Q1_2_APPROVED)}",
        "",
        "## 正式求解就绪性",
        "",
        f"- READY = {ready}",
        f"- 原因 = {reason}",
        "",
        "本阶段未运行正式 Q1-3 优化，未生成正式配送方案。",
        "",
    ]
    (RES / "q1_3_precheck_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(
        {"formal_solve_ready": ready, "blocker": reason,
         "capacity_status": cap_status, "n_boxes": s["n_boxes"]},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
