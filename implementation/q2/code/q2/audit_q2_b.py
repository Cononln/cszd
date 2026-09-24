# -*- coding: utf-8 -*-
"""Q2-B 运行入口：执行全部路线物理测试，生成 CSV / JSON / Markdown。

1. 读取正式数据；2. 运行全部测试；3. 生成 CSV；4. 生成 JSON；
5. 生成 Markdown；6. 打印 PASS/FAIL。不做调度、不优化、不绘图。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_route_evaluator as t  # noqa: E402

RESULTS = Path(__file__).resolve().parents[2] / "results"


def main() -> int:
    rows: list[dict] = []
    reg = t.test_single_stop_regression()
    rows += reg[0]
    reg_info = reg[1]
    rows += t.test_two_stop_payload_decrease()
    rows += t.test_three_stop_payload_decrease()
    rows += t.test_handover_accumulation()
    rows += t.test_order_sensitivity()
    rows += t.test_mass_infeasible()
    rows += t.test_volume_infeasible()
    rows += t.test_energy_infeasible()
    rows += t.test_duplicate_box()
    rows += t.test_sid_mismatch()
    rows += t.test_unknown_box()
    rows += t.test_empty_stop()

    df = pd.DataFrame(rows)
    assert df["pass"].all(), df.loc[~df["pass"], "case_id"].tolist()
    df.to_csv(RESULTS / "q2_b_route_cases.csv", index=False)

    by_id = {r["case_id"]: r for r in rows}
    checks = {
        "single_stop_regression_all": all(by_id[c]["pass"] for c in df["case_id"]
                                          if c.startswith("single-")),
        "payload_decreases_all": by_id["two-stop-payload"]["pass"]
        and by_id["three-stop-payload"]["pass"],
        "return_payload_zero_all": True,
        "handover_accumulation_pass": by_id["handover-accumulation"]["pass"],
        "order_sensitivity_verified": by_id["order-A-S001-S005"]["pass"]
        and by_id["order-B-S005-S001"]["pass"],
        "mass_infeasible_detected": by_id["mass-infeasible"]["pass"],
        "volume_infeasible_detected": by_id["volume-infeasible"]["pass"],
        "energy_infeasible_detected": by_id["energy-infeasible"]["pass"],
        "duplicate_box_rejected": by_id["duplicate-box"]["pass"],
        "sid_mismatch_rejected": by_id["sid-mismatch"]["pass"],
        "unknown_box_rejected": by_id["unknown-box"]["pass"],
        "empty_stop_rejected": by_id["empty-stop"]["pass"],
    }
    # 载荷递减与返程零载荷由逐案例 payload 序列复核
    for c in ("two-stop-payload", "three-stop-payload"):
        pls = [float(x) for x in by_id[c]["leg_payloads"].split(";")]
        checks["payload_decreases_all"] = checks["payload_decreases_all"] and all(
            b <= a + 1e-9 for a, b in zip(pls, pls[1:]))
        checks["return_payload_zero_all"] = checks["return_payload_zero_all"] and pls[-1] == 0.0
    status = "PASS" if all(checks.values()) else "FAIL"
    audit = {"phase": "Q2-B", "status": status, "checks": checks,
             "single_stop_regression": {"n_cases": 6,
                                        "max_time_error_s": reg_info["tmax"],
                                        "max_energy_error_kwh": reg_info["emax"]},
             "n_cases": len(rows)}
    (RESULTS / "q2_b_route_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# Q2-B 多点路线物理评价审计", "",
          "## 1. 单点退化一致性",
          "Q2 单点路线 = Q1 直接往返物理模型：6 组（A-S001/A-S015/B-S008/B-S012/C-S002/C-S008）"
          f"航段时间/能量与 Q1 直接计算一致，最大时间误差 {reg_info['tmax']:.3e}s，"
          f"最大能量误差 {reg_info['emax']:.3e}kWh。", "",
          "## 2. 多点载荷递减",
          "两站 O01-S001-S002-O01 载荷 [22,11,0]，三站 O01-S002-S005-S008-O01 载荷 [9,6,3,0]，"
          "严格单调不增且返程为 0。", "",
          "## 3. 多点能耗",
          "逐航段按本站剩余载荷调用 leg_energy，总能耗为各段之和；"
          "C 机 S008+S012 重载两站线能量超限被正确判否（margin<0）。", "",
          "## 4. 多站送达偏移",
          "送达偏移 = 准备/装载 + 沿途各段飞行 + 沿途各站交接；已验证后站偏移含前站交接"
          "（旧 B 版 P0 漏项回归）。", "",
          "## 5. 访问顺序差异",
          "同批货箱 S001-WAT-01(14kg)+S005-MED-01(3kg)：顺序 A 载荷 [17,3,0]，"
          "顺序 B 载荷 [17,14,0]，总能耗/时长/偏移均不同；本轮只证差异，不做顺序优化。", "",
          "## 6. 非法输入",
          "质量/体积/能量超限正确判否；重复 box、sid 错配、未知 box、空 stop 全部 raise。", "",
          f"## 结论：{status}"]
    (RESULTS / "q2_b_route_audit.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Q2-B: {len(rows)} cases, status={status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
