"""Q2-A data and deadline audit using the frozen Q1 common data layer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

Q2_DIR = Path(__file__).resolve().parents[2]
IMPL_DIR = Q2_DIR.parent
Q1_CODE = IMPL_DIR / "q1" / "code"
sys.path.insert(0, str(Q1_CODE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import (  # noqa: E402
    load_boxes,
    load_transport_batteries,
    load_transport_fleet,
)
from deadlines import add_deadline_columns  # noqa: E402

RESULTS = Q2_DIR / "results"


def _range_or_none(series: pd.Series) -> dict[str, float | None]:
    values = series.dropna()
    if values.empty:
        return {"min": None, "max": None}
    return {"min": float(values.min()), "max": float(values.max())}


def collect_audit() -> dict:
    boxes = add_deadline_columns(load_boxes())
    fleet = load_transport_fleet()
    batteries = load_transport_batteries()
    hard = boxes["hard_deadline_s"].dropna()
    first = boxes["first"]
    medical = boxes["type"].eq("医疗物资")
    checks = {
        "n_boxes_is_80": len(boxes) == 80,
        "n_service_areas_is_15": boxes["sid"].nunique() == 15,
        "fleet_is_8": len(fleet) == 8,
        "fleet_types_are_abc": set(fleet["gtype"]) == {"A", "B", "C"},
        "all_boxes_have_expected_time": int(boxes["t_exp"].isna().sum()) == 0,
        "all_hard_boxes_have_hard_deadline": int(boxes["hard_deadline_s"].isna().sum())
        == int((~first & ~medical).sum()),
    }
    return {
        "phase": "Q2-A",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "formal_optimization_run": False,
        "q1_common_reuse": [
            "implementation/q1/code/common/data.py",
            "implementation/q1/code/common/dem.py",
            "implementation/q1/code/common/physics.py",
            "implementation/q1/code/common/route.py",
        ],
        "boxes": {
            "n_boxes": int(len(boxes)),
            "n_service_areas": int(boxes["sid"].nunique()),
            "service_area_ids": sorted(boxes["sid"].unique().tolist()),
            "n_first_boxes": int(first.sum()),
            "n_medical_boxes": int(medical.sum()),
            "n_first_and_medical_boxes": int((first & medical).sum()),
            "n_hard_deadline_boxes": int(hard.notna().sum()),
            "mass_total_kg": float(boxes["mass"].sum()),
            "volume_total_m3": float(boxes["vol"].sum()),
            "type_counts": {str(k): int(v) for k, v in boxes["type"].value_counts().items()},
        },
        "fleet": {
            "n_uav": int(len(fleet)),
            "by_gtype": {str(k): int(v) for k, v in fleet["gtype"].value_counts().items()},
        },
        "batteries": {
            g: {"n": int(v["n"]), "t_full_s": float(v["t_full"])}
            for g, v in batteries.items()
        },
        "deadlines_s": {
            "t_first": _range_or_none(boxes["t_first"]),
            "t_exp": _range_or_none(boxes["t_exp"]),
            "hard_deadline": _range_or_none(boxes["hard_deadline_s"]),
            "missing_t_first": int(boxes["t_first"].isna().sum()),
            "missing_t_exp": int(boxes["t_exp"].isna().sum()),
        },
        "priority": {
            "min": float(boxes["prio"].min()),
            "max": float(boxes["prio"].max()),
            "mean": float(boxes["prio"].mean()),
        },
        "checks": checks,
        "notes": [
            "15 boxes are both first-batch and medical; hard_deadline takes min(t_first, t_exp).",
            "Q2 multi-stop energy and delivery offsets are not evaluated in Q2-A.",
            "No Q2 final route, WTD, Cmax, energy or Pareto result is produced in Q2-A.",
        ],
    }


def write_outputs(audit: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "q2_data_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    b = audit["boxes"]
    f = audit["fleet"]
    bat = audit["batteries"]
    d = audit["deadlines_s"]
    lines = [
        "# Q2-A 数据审计",
        "",
        f"- 状态：**{audit['status']}**",
        "- 正式优化：未运行（符合 Q2-A 阶段门）",
        f"- 货箱：{b['n_boxes']} 箱；服务区：{b['n_service_areas']} 个；",
        f"首批保障箱：{b['n_first_boxes']}；医疗物资箱：{b['n_medical_boxes']}；",
        f"同时属于两类：{b['n_first_and_medical_boxes']}；硬截止箱：{b['n_hard_deadline_boxes']}",
        f"- 运输无人机：{f['n_uav']} 架，按机型 {f['by_gtype']}",
        "- 共享电池："
        + "; ".join(f"{g}: {v['n']} 组, 满充 {v['t_full_s']:.0f}s" for g, v in bat.items()),
        f"- 首批截止范围：{d['t_first']['min']}–{d['t_first']['max']} s",
        f"- 期望送达范围：{d['t_exp']['min']}–{d['t_exp']['max']} s",
        f"- 统一硬截止范围：{d['hard_deadline']['min']}–{d['hard_deadline']['max']} s",
        f"- 优先系数范围：{audit['priority']['min']}–{audit['priority']['max']}，"
        f"均值 {audit['priority']['mean']:.3f}",
        "",
        "## 数据检查",
        "",
    ]
    for name, passed in audit["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: `{name}`")
    lines += ["", "## 口径说明", ""] + [f"- {note}" for note in audit["notes"]]
    (RESULTS / "q2_data_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = collect_audit()
    write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
