# -*- coding: utf-8 -*-
"""Q1-3 骨架单元测试（极小人工数据，不触及真实 80 箱与正式 q_max）。

覆盖：质量/体积/额定/唯一分配/全覆盖/非法服务区/候选枚举上限/正式入口锁定。
运行：.venv\\Scripts\\python.exe implementation/q1/tests/test_q1_batching.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code" / "q1"))

import q1_batching as qb


def t1_single_box_fits():
    assert qb.check_single_service_mass_capacity(5.0, 10.0) is True
    assert qb.check_volume_capacity(0.05, 0.5) is True
    assert qb.check_rated_mass(5.0, 25.0) is True


def t2_mass_over_qmax_fails():
    assert qb.check_single_service_mass_capacity(10.5, 10.0) is False


def t3_volume_over_V_fails():
    assert qb.check_volume_capacity(0.6, 0.5) is False


def t4_mass_ok_volume_fail():
    assert qb.check_single_service_mass_capacity(5.0, 10.0) is True
    assert qb.check_volume_capacity(0.6, 0.5) is False


def t5_volume_ok_mass_fail():
    assert qb.check_volume_capacity(0.05, 0.5) is True
    assert qb.check_single_service_mass_capacity(30.0, 25.0) is False


def t6_duplicate_box_detected():
    ok, dupes = qb.check_box_assignment_unique({"B1": "T1", "B2": "T1"})
    assert ok is True and dupes == []
    # 同一箱被两个架次申领必须检出为未通过
    ok2, dupes2 = qb.check_box_assignment_unique([("B1", "T1"), ("B1", "T2")])
    assert ok2 is False and dupes2 == ["B1"]


def t7_unassigned_box_detected():
    ok, problems = qb.check_all_boxes_assigned(["B1", "B2", "B3"], {"B1": "T1"})
    assert ok is False and set(problems) == {"B2", "B3"}


def t8_illegal_sid_and_capacity_gate():
    df = pd.DataFrame([{"sid": "S999", "gtype": "A", "rated_payload_kg": 25.0,
                         "q_max_kg": 25.0, "q_max_ratio": 1.0,
                         "capacity_status": "RATED_CAPACITY", "qmax_feasible": True}])
    struct = qb.validate_capacity_table(df)
    assert struct["all_structural_pass"] is False  # 非法 sid/行数不足
    status, _ = qb.load_q1_capacity(path=Path("nonexistent_q1_capacity.csv"))
    assert status == qb.CAPACITY_STATUS_WAITING
    try:
        qb.solve_q1()
        raise AssertionError("solve_q1 must stay locked")
    except RuntimeError:
        pass


def t9_candidate_enum_small_and_guarded():
    boxes = [qb.BoxItem(box_id=f"X{i}", sid="S001", mass=1.0, volume=0.01,
                        is_first=False) for i in range(3)]
    cands = qb.generate_single_service_candidate_batches(boxes, "A", 2.5, 0.05)
    assert len(cands) == 6  # C3,1 + C3,2 = 3 + 3（三箱全选超质量）
    big = [qb.BoxItem(box_id=f"Y{i}", sid="S001", mass=1.0, volume=0.01,
                      is_first=False) for i in range(13)]
    try:
        qb.generate_single_service_candidate_batches(big, "A", 100.0, 10.0)
        raise AssertionError("enumeration guard must refuse large inputs")
    except ValueError:
        pass


def main() -> int:
    tests = [t1_single_box_fits, t2_mass_over_qmax_fails, t3_volume_over_V_fails,
             t4_mass_ok_volume_fail, t5_volume_ok_mass_fail, t6_duplicate_box_detected,
             t7_unassigned_box_detected, t8_illegal_sid_and_capacity_gate,
             t9_candidate_enum_small_and_guarded]
    for i, fn in enumerate(tests, 1):
        fn()
        print(f"test{i} {fn.__name__}: PASS")
    print(f"ALL {len(tests)} SKELETON TESTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
